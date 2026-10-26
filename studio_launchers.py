"""Optional workflow shortcuts. Studio launches in the browser, not the queue."""

class ZuraStudioLauncher:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {}}

    RETURN_TYPES = ()
    FUNCTION = 'launch'
    CATEGORY = 'Zura/Studio'
    DESCRIPTION = 'Open Zura Studio using the button on this node. No connections or queued generation are needed.'

    def launch(self):
        return ()


class ZuraPaintoutStudioLauncher(ZuraStudioLauncher):
    DESCRIPTION = 'Open Paintout Studio using the button on this node. Local masks, clean frames and VFX paintout.'


NODE_CLASS_MAPPINGS = {'ZuraStudioLauncher': ZuraStudioLauncher, 'ZuraPaintoutStudioLauncher': ZuraPaintoutStudioLauncher}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraStudioLauncher': 'Open Zura Studio', 'ZuraPaintoutStudioLauncher': 'Open Paintout Studio'}
