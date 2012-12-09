<%!
    from sailfish import sym
    import sailfish.node_type as nt
%>

%if 'gravity' in context.keys():
	${const_var} float gravity = ${gravity}f;
%endif

<%def name="bgk_args_decl()">
	float rho, float *iv0
	%if simtype == 'shan-chen':
		, float *ea0
	%endif
</%def>

<%def name="bgk_args()">
	g0m0, v
	%if simtype == 'shan-chen':
		, sca0
	%endif
</%def>

%if subgrid != 'les-smagorinsky':
	${const_var} float tau0 = ${tau}f;		// relaxation time
%endif
${const_var} float visc = ${visc}f;		// viscosity

<%namespace file="kernel_common.mako" import="*" name="kernel_common"/>
${kernel_common.body(bgk_args_decl)}

%if simtype == 'shan-chen':
	<%namespace file="shan_chen.mako" import="*" name="shan_chen"/>
	${shan_chen.body()}
%endif

<%namespace file="opencl_compat.mako" import="*" name="opencl_compat"/>
<%namespace file="code_common.mako" import="*"/>
<%namespace file="boundary.mako" import="*" name="boundary"/>
<%namespace file="relaxation.mako" import="*" name="relaxation"/>
<%namespace file="propagation.mako" import="*"/>
<%namespace file="utils.mako" import="*"/>

<%def name="init_dist_with_eq()">
	<% eq = equilibria[0](grid, config) %>

	%for local_var in eq.local_vars:
		float ${cex(local_var.lhs)} = ${cex(local_var.rhs)};
	%endfor

	%if nt.NTGradFreeflow in node_types:
		Dist d0;
	%endif

	%for i, (feq, idx) in enumerate(zip(eq.expression, grid.idx_name)):
		${get_odist('dist1_in', i)} = ${cex(feq)};
		%if nt.NTGradFreeflow in node_types:
			d0.${idx} = ${cex(feq)};
		%endif
	%endfor
</%def>

<%def name="prepare_grad_node()">
	int ncode = map[gi];
	int type = decodeNodeType(ncode);

	if (isNTGradFreeflow(type)) {
		int scratch_id = decodeNodeScratchId(ncode);
		float flux[${flux_components}];
		compute_2nd_moment(&d0, flux);
		storeNodeScratchSpace(scratch_id, type, flux, node_scratch_space);

		// Iterate over all neighbours, mark all distributions coming from ghost
		// nodes with an invalid value (infinity).
		int gx_n, gy_n;
		%if dim > 2:
			int gz_n;
		%endif
		int gi_n, ncode_n, type_n;
		%for i, ve in enumerate(grid.basis):
			gx_n = gx + (${ve[0]});
			gy_n = gy + (${ve[1]});
			%if dim > 2:
				gz_n = gz + (${ve[2]});
			%endif
			%if dim == 2:
				gi_n = getGlobalIdx(gx_n, gy_n);
			%else:
				gi_n = getGlobalIdx(gx_n, gy_n, gz_n);
			%endif
			ncode_n = map[gi_n];
			type_n = decodeNodeType(ncode_n);
			if (is_NTGhost(type_n)) {
				dist1_in[gi + DIST_SIZE * ${grid.idx_opposite[i]} + 0] = 1 / 0.;
			}
		%endfor
	}
</%def>

// A kernel to set the node distributions using the equilibrium distributions
// and the macroscopic fields.
${kernel} void SetInitialConditions(
	${global_ptr} float *dist1_in,
	${kernel_args_1st_moment('iv')}
	${global_ptr} float *irho, int *map
	${scratch_space_if_required()})
{
	${local_indices()}

	// Cache macroscopic fields in local variables.
	float rho = irho[gi] ${' -1.0f' if config.minimize_roundoff else ''};
	float v0[${dim}];

	v0[0] = ivx[gi];
	v0[1] = ivy[gi];
	%if dim == 3:
		v0[2] = ivz[gi];
	%endif

	${init_dist_with_eq()}

	%if nt.NTGradFreeflow in node_types:
		${prepare_grad_node()}
	%endif
}

${kernel} void PrepareMacroFields(
	${global_ptr} int *map,
	${global_ptr} float *dist1_in,
	${global_ptr} float *orho,
	int options
	${scratch_space_if_required()}
	${iteration_number_if_required()})
{
	${local_indices_split()}

	int ncode = map[gi];
	int type = decodeNodeType(ncode);

	// Unused nodes do not participate in the simulation.
	if (isExcludedNode(type))
		return;

	int orientation = decodeNodeOrientation(ncode);

	Dist fi;
	float out;

	getDist(&fi, dist1_in, gi ${iteration_number_arg_if_required()});
	get0thMoment(&fi, type, orientation, &out);
	orho[gi] = out;
}

${kernel} void CollideAndPropagate(
	${global_ptr} int *map,
	${global_ptr} float *dist_in,
	${global_ptr} float *dist_out,
	${global_ptr} float *gg0m0,
	${kernel_args_1st_moment('ov')}
	int options
	${scratch_space_if_required()}
	${iteration_number_if_required()}
	${scalar_field_if_required('alpha', alpha_output)}
	)
{
	${local_indices_split()}

	// Shared variables for in-block propagation
	%for i in sym.get_prop_dists(grid, 1):
		${shared_var} float prop_${grid.idx_name[i]}[BLOCK_SIZE];
	%endfor
	%for i in sym.get_prop_dists(grid, 1):
		#define prop_${grid.idx_name[grid.idx_opposite[i]]} prop_${grid.idx_name[i]}
	%endfor

	int ncode = map[gi];
	int type = decodeNodeType(ncode);

	// Unused nodes do not participate in the simulation.
	if (isExcludedNode(type))
		return;

	int orientation = decodeNodeOrientation(ncode);

	// Cache the distributions in local variables
	Dist d0;
	getDist(&d0, dist_in, gi ${iteration_number_arg_if_required()});
	fixMissingDistributions(&d0, dist_in, ncode, type, orientation, gi,
							ovx, ovy ${', ovz' if dim == 3 else ''}, gg0m0
							${scratch_space_arg_if_required()});

	%if simtype == 'shan-chen':
		${sc_calculate_accel()}
	%endif

	// Macroscopic quantities for the current cell
	float g0m0, v[${dim}];

	%if simtype == 'shan-chen':
		${sc_macro_fields()}
	%else:
		getMacro(&d0, ncode, type, orientation, &g0m0, v ${dynamic_val_call_args()});
	%endif

	precollisionBoundaryConditions(&d0, ncode, type, orientation, &g0m0, v);
	${relaxate(bgk_args)}
	postcollisionBoundaryConditions(&d0, ncode, type, orientation, &g0m0, v, gi, dist_out
									${scratch_space_arg_if_required()});

	## Grad outflow nodes use invalid values to tag directions lacking distribution
	## data.
	if (isWetNode(type) ${'&& !isNTGradFreeflow(type)' if nt.NTGradFreeflow in node_types else ''}) {
		checkInvalidValues(&d0, ${position()});
	}

	// Only save the macroscopic quantities if requested to do so.
	if ((options & OPTION_SAVE_MACRO_FIELDS)
		## Nodes using the Grad approximation use the velocity from the
		## previous time step to compute the approximated distributions.
		${'|| isNTGradFreeflow(type)' if nt.NTGradFreeflow in node_types else ''}) {
		gg0m0[gi] = g0m0 ${' +1.0f' if config.minimize_roundoff else ''};
		ovx[gi] = v[0];
		ovy[gi] = v[1];
		%if dim == 3:
			ovz[gi] = v[2];
		%endif
	}

	${propagate('dist_out', 'd0')}
}

<%include file="util_kernels.mako"/>
