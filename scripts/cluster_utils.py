"""Shared helpers for the code-level theme pipeline: array caching and Leiden clustering.

Kept separate from cluster_themes.py (the paragraph-level BERTopic baseline) so that pipeline
stays untouched as a comparison point.
"""

from __future__ import annotations

import colorsys
from pathlib import Path
from typing import Callable, Hashable

import igraph as ig
import leidenalg
import numpy as np
from sklearn.neighbors import NearestNeighbors

GOLDEN_ANGLE = 0.6180339887  # successive hues this far apart stay maximally distinct at any n


def golden_angle_palette(labels: list[Hashable]) -> dict[Hashable, str]:
    """Distinct hex color per label, spaced via the golden angle so that labels adjacent in
    the input order (e.g. themes numbered by descending size) don't get visually similar hues."""
    unique = sorted(set(labels), key=labels.index)
    colors = {}
    for i, label in enumerate(unique):
        hue = (i * GOLDEN_ANGLE) % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, 0.55, 0.65)
        colors[label] = "#{:02x}{:02x}{:02x}".format(int(r * 255), int(g * 255), int(b * 255))
    return colors


def cached_array(cache_dir: Path, name: str, keys: list[str], compute_fn: Callable[[], np.ndarray]) -> np.ndarray:
    """Load a cached array if it was computed for exactly these keys, else compute and cache it."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    data_path = cache_dir / f"{name}.npy"
    keys_path = cache_dir / f"{name}_keys.npy"

    if data_path.exists() and keys_path.exists():
        cached_keys = np.load(keys_path, allow_pickle=True)
        if list(cached_keys) == keys:
            return np.load(data_path)

    result = compute_fn()
    np.save(data_path, result)
    np.save(keys_path, np.array(keys, dtype=object))
    return result


def build_knn_graph(embeddings: np.ndarray, k: int = 10) -> ig.Graph:
    """Symmetric kNN graph on cosine similarity, weighted by similarity.

    Clusters on the full-dimensional embeddings - never on 2-D projection coordinates, which
    destroy the local distinctions clustering depends on. Use a 2-D UMAP for display only.
    """
    n = len(embeddings)
    nn = NearestNeighbors(n_neighbors=min(k + 1, n), metric="cosine").fit(embeddings)
    distances, indices = nn.kneighbors(embeddings)

    edges: dict[tuple[int, int], float] = {}
    for i in range(n):
        for dist, j in zip(distances[i], indices[i]):
            if i == int(j):
                continue
            edge = (min(i, int(j)), max(i, int(j)))
            edges[edge] = max(edges.get(edge, 0.0), float(1 - dist))

    graph = ig.Graph(n=n, edges=list(edges.keys()))
    graph.es["weight"] = list(edges.values())
    return graph


def leiden_partition(embeddings: np.ndarray, k: int = 10, resolution: float = 1.0, seed: int = 42) -> list[int]:
    """Leiden community detection over a kNN graph of the embeddings.

    Returns a membership list aligned with the embedding rows. Higher resolution -> more,
    smaller communities; running the same graph at several resolutions is how the theme
    hierarchy in build_themes.py is produced.
    """
    graph = build_knn_graph(embeddings, k=k)
    partition = leidenalg.find_partition(
        graph,
        leidenalg.RBConfigurationVertexPartition,
        weights=graph.es["weight"],
        resolution_parameter=resolution,
        seed=seed,
    )
    return list(partition.membership)
