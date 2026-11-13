"""Reserve only public Studio handler pairs before helper registration."""


def require_studio_alias_paths(routes, operations):
    """Refuse collisions without adding or replacing any route in this helper.

    aiohttp can retain duplicate non-consecutive resources, so application
    routing alone is not a collision check. GET also reserves its automatic
    HEAD route. Different methods at the same path remain independent.
    """
    # StaticDef entries have no HTTP method; unrelated static resources are
    # allowed alongside these exact public API routes.
    existing={(getattr(route,'method',None),getattr(route,'path',None)) for route in routes}
    requested=set()
    for method,suffix in operations:
        if method not in ('GET','POST') or not isinstance(suffix,str) or any(
                not part or part in ('.','..') for part in suffix.split('/')):
            raise ValueError('Choose a fixed public Studio helper route.')
        methods=(method,'HEAD') if method=='GET' else (method,)
        for namespace in ('zura','genj'):
            path='/'+namespace+'/studio/'+suffix
            for verb in methods:
                key=(verb,path)
                if key in requested:raise RuntimeError('Duplicate public Studio helper route: '+verb+' '+path)
                if key in existing or ('*',path) in existing:raise RuntimeError('Public Studio route already registered: '+verb+' '+path)
                requested.add(key)
