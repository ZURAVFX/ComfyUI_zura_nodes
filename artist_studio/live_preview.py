"""Select supported tiny decoders per job without changing Comfy's global default."""


def preview_method(config, stage, filenames=None):
    if filenames is None:
        try:
            import folder_paths
            filenames = folder_paths.get_filename_list("vae_approx")
        except (ImportError, AttributeError, KeyError):
            filenames = []
    files = {str(name).replace("\\", "/").rsplit("/", 1)[-1].lower() for name in filenames}
    # Wan 14B uses the 2.1 VAE. The 2.2 tiny decoder is for the 5B VAE.
    decoder = ("taeh3.safetensors" if stage == "h3" else
               "lighttaew2_1.safetensors" if stage in ("wan", "wan2", "wan21_relight") else None)
    return "taesd" if decoder and decoder in files else "auto"
