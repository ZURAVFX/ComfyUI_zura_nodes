# Artist graph layout checkpoint

Studio exports use native subgraphs with visible reference-image loaders. Main stages run from left to right with routed native connections. Orthogonal wire drawing applies only to Studio-authored graphs and restores the user's canvas setting afterwards.

Graph import or layout failure restores the previous workflow instead of exposing an unarranged API export. Main-graph crossings reject the handoff. Native interface connections are created in destination order, preserving media links and promoted artist controls.

Verification: 28 JavaScript checks pass. Offline native graph qualification covers H3, H3 viewport, starting-image design and Wan exports, including render-input equivalence and reload. The qualification uses frontend 1.53.10 with current node schemas; installed frontend 1.55.17 APIs were inspected separately. This is structural verification, not visual sign-off in Comfy Desktop.

Remaining work: the H3 viewport reference-conditioning subgraph still has three internal crossings. Finish those routes and obtain visual approval of the main graph before declaring the layout complete. This checkpoint is a development candidate, not a final release.
