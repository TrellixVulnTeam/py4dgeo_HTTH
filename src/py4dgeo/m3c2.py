from py4dgeo.epoch import Epoch, as_epoch
from py4dgeo.util import (
    as_double_precision,
    as_single_precision,
    get_memory_policy,
    MemoryPolicy,
    Py4DGeoError,
    get_memory_policy,
    make_contiguous,
    memory_policy_is_minimum,
)

import abc
import numpy as np
import typing

import py4dgeo._py4dgeo as _py4dgeo


class M3C2LikeAlgorithm(abc.ABC):
    def __init__(
        self,
        epochs: typing.Tuple[Epoch, ...],
        corepoints: np.ndarray = None,
        radii: typing.List[float] = None,
        max_cylinder_length: float = 0.0,
        calculate_uncertainty: bool = True,
    ):
        self.epochs = epochs
        self.corepoints = as_single_precision(make_contiguous(corepoints))
        self.radii = radii
        self.max_cylinder_length = max_cylinder_length
        self.calculate_uncertainty = calculate_uncertainty

        # Check the given array shapes
        if len(self.corepoints.shape) != 2 or self.corepoints.shape[1] != 3:
            raise Py4DGeoError("Corepoints need to be given as an array of shape nx3")

        # Check the given radii
        if self.radii is None or len(self.radii) == 0:
            raise Py4DGeoError(f"{self.name} requires at least one radius to be given")

        # Check the given number of epochs
        self.check_number_of_epochs()

    @property
    def name(self):
        raise NotImplementedError

    def directions(self):
        """The normal direction(s) to use for this algorithm."""
        raise NotImplementedError

    def check_number_of_epochs(self):
        if len(self.epochs) != 2:
            raise Py4DGeoError(
                f"{self.name} only operates on exactly 2 epochs, {len(self.epochs)} given!"
            )

    def calculate_distances(self, epoch1, epoch2):
        """Calculate the distances between two epochs"""

        assert len(self.radii) == 1

        # Extract the uncertainty callback
        uncertainty_callback = self.callback_uncertainty_calculation()
        if not self.calculate_uncertainty:
            uncertainty_callback = _py4dgeo.no_uncertainty

        distances, uncertainties = _py4dgeo.compute_distances(
            self.corepoints,
            self.radii[0],
            epoch1,
            epoch2,
            self.directions(),
            self.max_cylinder_length,
            self.callback_workingset_finder(),
            uncertainty_callback,
        )

        return distances, uncertainties

    def run(self):
        """Main entry point for running the algorithm"""
        return self.calculate_distances(self.epochs[0], self.epochs[1])

    def callback_workingset_finder(self):
        """The callback used to determine the point cloud subset around a corepoint"""
        return _py4dgeo.cylinder_workingset_finder

    def callback_uncertainty_calculation(self):
        """The callback used to calculate the uncertainty"""
        return _py4dgeo.standard_deviation_uncertainty


class M3C2(M3C2LikeAlgorithm):
    def __init__(
        self,
        scales: typing.List[float] = None,
        orientation_vector: np.ndarray = np.array([0, 0, 1]),
        corepoint_normals: np.ndarray = None,
        cloud_for_normals: Epoch = None,
        **kwargs,
    ):
        self.scales = scales
        self.orientation_vector = as_double_precision(
            make_contiguous(orientation_vector), policy_check=False
        )
        self.cloud_for_normals = cloud_for_normals
        self.corepoint_normals = corepoint_normals
        super().__init__(**kwargs)

    def directions(self):
        # If we already have normals, we return them. This happens e.g. if the user
        # explicitly provided them or if we already computed them in a previous run.
        if self.corepoint_normals is not None:
            # Make sure that the normals use double precision
            self.corepoint_normals = as_double_precision(self.corepoint_normals)

            # Assert that the normal array has the correct shape
            if (
                len(self.corepoint_normals.shape) != 2
                or self.corepoint_normals.shape[0] not in (1, self.corepoints.shape[0])
                or self.corepoint_normals.shape[1] != 3
            ):
                raise Py4DGeoError(
                    f"Incompative size of corepoint normal array {self.corepoint_normals.shape}, expected {self.corepoints.shape} or (1, 3)!"
                )

            return self.corepoint_normals

        # This does not work in STRICT mode
        if not memory_policy_is_minimum(MemoryPolicy.MINIMAL):
            raise Py4DGeoError(
                "M3C2 requires at least the MINIMUM memory policy level to compute multiscale normals"
            )

        # Allocate the storage for the computed normals
        self.corepoint_normals = np.empty(self.corepoints.shape, dtype=np.float64)

        # Find the correct epoch to use for normal calculation
        normals_epoch = self.cloud_for_normals
        if normals_epoch is None:
            normals_epoch = self.epochs[0]
        normals_epoch = as_epoch(normals_epoch)

        # Trigger the precomputation
        _py4dgeo.compute_multiscale_directions(
            normals_epoch,
            self.corepoints,
            self.scales,
            self.orientation_vector,
            self.corepoint_normals,
        )

        return self.corepoint_normals

    @property
    def name(self):
        return "M3C2"
