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
    DEPRECATED = True
    DESCRIPTION = 'Legacy shortcut. Opens Video > Paintout / clean plate inside Zura Studio. Use Open Zura Studio in new workflows.'


NODE_CLASS_MAPPINGS = {'ZuraStudioLauncher': ZuraStudioLauncher, 'ZuraPaintoutStudioLauncher': ZuraPaintoutStudioLauncher}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraStudioLauncher': 'Open Zura Studio', 'ZuraPaintoutStudioLauncher': 'Open Zura Studio (legacy Paintout shortcut)'}
