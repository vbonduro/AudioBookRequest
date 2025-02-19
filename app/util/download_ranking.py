from app.models import ProwlarrSource

MIN_SEEDERS = 5
MIN_SEED_RATIO = 2.0


# TODO: This could be replaced with Readarr's quality/ranking system if that works well
def rank_sources(sources: list[ProwlarrSource]) -> list[ProwlarrSource]:
    sorted_seeders = sorted(sources, key=lambda x: x.seeders, reverse=True)
    for i, source in enumerate(sorted_seeders):
        leechers = max(source.leechers, 1)
        if source.seeders < MIN_SEEDERS or source.seeders / leechers < MIN_SEED_RATIO:
            continue

        source.download_score = len(sorted_seeders) - i

    return sorted(sources, key=lambda x: x.download_score, reverse=True)
