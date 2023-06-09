from typing import Dict

import torch as th
import torch.nn as nn
from gymnasium import spaces

from stable_baselines3.common.preprocessing import get_flattened_obs_dim
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

from maze_game.sb3_tests.maze_cnn import MazeCNN, StatsCNN, WallsCNN, TreasuresCNN


class CustomCombinedExtractor(BaseFeaturesExtractor):
    def __init__(
            self,
            observation_space: spaces.Dict,
            cnn_output_dim: int = 128,
    ) -> None:
        super().__init__(observation_space, features_dim=1)

        extractors: Dict[str, nn.Module] = {}

        total_concat_size = 0
        for key, subspace in observation_space.spaces.items():
            if key == "field":
                extractors[key] = MazeCNN(subspace, features_dim=256)
                total_concat_size += 128
            elif key == "walls":
                extractors[key] = WallsCNN(subspace, features_dim=256)
                total_concat_size += 128
            elif key == "treasures":
                extractors[key] = TreasuresCNN(subspace, features_dim=32)
                total_concat_size += 32
            elif key == "stats":
                extractors[key] = StatsCNN(subspace, features_dim=12)
                total_concat_size += 12
            else:
                # Run through a simple MLP
                extractors[key] = nn.Flatten()
                total_concat_size += get_flattened_obs_dim(subspace)

        self.extractors = nn.ModuleDict(extractors)

        # Update the features dim manually
        self._features_dim = total_concat_size

    def forward(self, observations) -> th.Tensor:
        encoded_tensor_list = []

        # self.extractors contain nn.Modules that do all the processing.
        for key, extractor in self.extractors.items():
            encoded_tensor_list.append(extractor(observations[key]))
        # Return a (B, self._features_dim) PyTorch tensor, where B is batch dimension.
        return th.cat(encoded_tensor_list, dim=1)
