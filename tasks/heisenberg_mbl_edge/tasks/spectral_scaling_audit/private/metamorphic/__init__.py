"""Private metamorphic infrastructure for the spectral scaling audit."""

from .harness import (
    assert_packet_equivalent,
    compare_output_directories,
    rejoin_shards,
    run_analyzer,
    run_metamorphic_suite,
    split_case_into_shards,
    transform_affine_control,
    transform_positive_affine_energy,
    transform_realization_id_permutation,
    transform_row_and_packet_permutation,
    transform_target_mirror,
)

__all__ = [
    "assert_packet_equivalent",
    "compare_output_directories",
    "rejoin_shards",
    "run_analyzer",
    "run_metamorphic_suite",
    "split_case_into_shards",
    "transform_affine_control",
    "transform_positive_affine_energy",
    "transform_realization_id_permutation",
    "transform_row_and_packet_permutation",
    "transform_target_mirror",
]

