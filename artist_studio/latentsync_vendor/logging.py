"""Keep the upstream logger without importing training/video utilities."""
def zero_rank_log(logger, message):
    logger.info(message)
