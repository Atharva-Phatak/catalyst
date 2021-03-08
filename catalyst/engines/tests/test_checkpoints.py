# flake8: noqa
from typing import Any, Dict, List
import logging
import os
from tempfile import TemporaryDirectory

from pytest import mark
import torch
from torch.utils.data import DataLoader

from catalyst.callbacks import CheckpointCallback, CriterionCallback, OptimizerCallback
from catalyst.core.runner import IRunner
from catalyst.engines.device import DeviceEngine
from catalyst.loggers import ConsoleLogger, CSVLogger
from catalyst.runners.config import SupervisedConfigRunner
from catalyst.settings import IS_CUDA_AVAILABLE, NUM_CUDA_DEVICES

from .misc import (
    DeviceCheckCallback,
    DummyDataset,
    DummyModel,
    LossMinimizationCallback,
    ModuleTypeChecker,
    CheckModelStateLoadAfterStages,
)

logger = logging.getLogger(__name__)


if NUM_CUDA_DEVICES > 1:
    os.environ["MKL_SERVICE_FORCE_INTEL"] = "1"

# experiment definition
class CustomRunner(IRunner):
    def __init__(self, logdir, device):
        super().__init__()
        self._logdir = logdir
        self._device = device

    def get_engine(self):
        return DeviceEngine(self._device)

    def get_callbacks(self, stage: str):
        return {
            "criterion": CriterionCallback(
                metric_key="loss", input_key="logits", target_key="targets"
            ),
            "optimizer": OptimizerCallback(metric_key="loss"),
            # "scheduler": dl.SchedulerCallback(loader_key="valid", metric_key="loss"),
            "checkpoint": CheckpointCallback(
                self._logdir,
                loader_key="valid",
                metric_key="loss",
                minimize=True,
                save_n_best=3,
                load_on_stage_start="best",  # download best state
            ),
            "test_nn_module": ModuleTypeChecker(),
            "test_device": DeviceCheckCallback(self._device, logger=logger),
            # "test_loss_minimization": LossMinimizationCallback("loss", logger=logger),
            "test_model_state_after_stage": CheckModelStateLoadAfterStages(
                "second", self._logdir, "best.pth"
            ),
        }

    @property
    def stages(self) -> "Iterable[str]":
        return ["first", "second"]

    def get_stage_len(self, stage: str) -> int:
        stage_epochs_map = {"first": 4, "second": 1}
        return stage_epochs_map[stage]

    def get_loaders(self, stage: str):
        dataset = DummyDataset(6)
        loader = DataLoader(dataset, batch_size=4)
        return {"train": loader, "valid": loader}

    def get_model(self, stage: str):
        return DummyModel(4, 2)

    def get_criterion(self, stage: str):
        return torch.nn.MSELoss()

    def get_optimizer(self, model, stage: str):
        return torch.optim.Adam(model.parameters())

    def get_scheduler(self, optimizer, stage: str):
        return None

    def get_trial(self):
        return None

    def get_loggers(self):
        return {"console": ConsoleLogger(), "csv": CSVLogger(logdir=self._logdir)}

    def handle_batch(self, batch):
        x, y = batch
        logits = self.model(x)

        self.batch = {"features": x, "targets": y, "logits": logits}


def run_train_with_experiment_device(device):
    with TemporaryDirectory() as logdir:
        runner = CustomRunner(logdir, device)
        runner.run()


def run_train_with_config_experiment_device(device):
    with TemporaryDirectory() as logdir:
        dataset = DummyDataset(6)
        runner = SupervisedConfigRunner(
            config={
                "args": {"logdir": logdir},
                "model": {"_target_": "DummyModel", "in_features": 4, "out_features": 2},
                "engine": {"_target_": "DeviceEngine", "device": device},
                "args": {"logdir": logdir},
                "stages": {
                    "stage1": {
                        "num_epochs": 10,
                        "criterion": {"_target_": "MSELoss"},
                        "optimizer": {"_target_": "Adam", "lr": 1e-3},
                        "loaders": {"batch_size": 4, "num_workers": 0},
                        "callbacks": {
                            "criterion": {
                                "_target_": "CriterionCallback",
                                "metric_key": "loss",
                                "input_key": "logits",
                                "target_key": "targets",
                            },
                            "optimizer": {"_target_": "OptimizerCallback", "metric_key": "loss"},
                            "test_nn_module": {"_target_": "ModuleTypeChecker"},
                            "test_device": {
                                "_target_": "DeviceCheckCallback",
                                "assert_device": device,
                            },
                            "test_loss_minimization": {
                                "_target_": "LossMinimizationCallback",
                                "key": "loss",
                            },
                        },
                    },
                },
            }
        )
        runner.get_datasets = lambda *args, **kwargs: {
            "train": dataset,
            "valid": dataset,
        }
        runner.run()


def test_engine_checkpoint_load():
    # will check on all available devices
    to_check_devices = ["cpu"] + [f"cuda:{i}" for i in range(NUM_CUDA_DEVICES)]
    for device in to_check_devices:
        run_train_with_experiment_device(device)


# def test_config_engine_checkpoint_load():
#     # will check on all available devices
#     to_check_devices = ["cpu"] + [f"cuda:{i}" for i in range(NUM_CUDA_DEVICES)]
#     for device in to_check_devices:
#         run_train_with_config_experiment_device(device)
