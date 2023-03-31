from enum import IntEnum
import random
from typing import Generator

import gymnasium as gym
from gymnasium import spaces
import pygame
import numpy as np

from maze_game.game_map_encoder import encode
from maze_game.game_core import SpectatorGUI, Game, Directions, Actions as Acts
from maze_game.game_core import base_rules as ru


class MazeGameEnv(gym.Env):
    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 100}

    # Enumeration of possible actions
    class Actions(IntEnum):
        # move directions
        move_top = 0
        move_right = 1
        move_bottom = 2
        move_left = 3

        # bombing directions
        # bomb_top = 4
        # bomb_right = 5
        # bomb_bottom = 6
        # bomb_left = 7

        # Pick up an object
        swap_treasure = 4

        # get info
        # info = 5

    def __init__(self, render_mode=None, size=5, max_steps=250):
        self.size = size
        self.max_steps = max_steps

        self.gui: SpectatorGUI | None = None
        self.rules = {}
        self.players = []
        self.turns: list | Generator = []

        self.step_count = 0

        self.response = None

        self._setup_game_local()
        self.game = Game(rules=self.rules)
        field = self.game.field
        for i, player in enumerate(self.players, 1):
            field.spawn_player(*player, turn=i)

        self._make_init_turns()

        field_observation_space = spaces.Box(
            low=0,
            high=255,
            shape=(self.size + 2, self.size + 2, 3),
            dtype=np.uint8,
        )
        self.observation_space = spaces.Dict(
            {
                "field": field_observation_space,
                "stats": spaces.Box(0, 5, shape=(6,), dtype=np.uint8),
            }
        )

        self.actions = MazeGameEnv.Actions
        self.action_space = spaces.Discrete(len(self.actions))

        """
        The following dictionary maps abstract actions from `self.action_space` to 
        the direction we will walk in if that action is taken.
        """
        self._action_space_to_action = {
            0: (Acts.move, Directions.top),
            1: (Acts.move, Directions.right),
            2: (Acts.move, Directions.bottom),
            3: (Acts.move, Directions.left),

            # 4: (Acts.throw_bomb, Directions.top),
            # 5: (Acts.throw_bomb, Directions.right),
            # 6: (Acts.throw_bomb, Directions.bottom),
            # 7: (Acts.throw_bomb, Directions.left),

            4: (Acts.swap_treasure, None),
            # 100: (Acts.info, None)
        }

        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode

    def _setup_game_local(self, seed=None):
        self.rules = ru
        # self.rules['generator_rules']['river_rules']['has_river'] = False
        self.rules['generator_rules']['walls']['has_walls'] = False
        # self.rules['generator_rules']['exits_amount'] = 20
        self.rules['generator_rules']['rows'] = self.size
        self.rules['generator_rules']['cols'] = self.size
        self.rules['generator_rules']['is_separated_armory'] = True
        self.rules['generator_rules']['seed'] = random.random() if seed is None else seed
        # self.rules['generator_rules']['seed'] = 1
        # self.rules['generator_rules']['levels_amount'] = 2
        self.rules['gameplay_rules']['fast_win'] = False
        self.rules['gameplay_rules']['diff_outer_concrete_walls'] = True
        # self.rules['generator_rules']['river_rules']['min_coverage'] = 90
        # self.rules['generator_rules']['river_rules']['max_coverage'] = 100
        spawn: dict[str, int] = {'x': 5, 'y': 3}
        spawn2: dict[str, int] = {'x': 2, 'y': 4}
        spawn3: dict[str, int] = {'x': 2, 'y': 1}

        self.players = [
            (spawn, 'Skipper'),
            # (spawn2, 'Tester'),
            # (spawn3, 'player'),
        ]
        self.turns = []

    def _make_init_turns(self):
        for _ in self.players:
            act = (Acts.info, None)
            is_running = self._process_turn(*act)

    def _process_turn(self, action: Acts, direction: Directions):
        response, next_player = self.game.make_turn(action.name, direction.name if direction else None)
        self.success = False
        if response is not None:
            self.response = response
            self.success = True
        # print(response.get_turn_info(), response.get_info())
        # if self.bot:
        #     # print(response.get_raw_info())
        #     self.bot.process_turn_resp(response.get_raw_info())
        #     self.bot.turn_prepare(self.game.get_current_player().name)
        if self.game.is_win_condition(self.rules):
            return False
        return True

    def get_allowed_actions_mask(self):
        act_pl_abilities = self.game.get_allowed_abilities(self.game.get_current_player())
        mask = [1 if act_pl_abilities.get(self._action_space_to_action[action][0]) else 0 for action in self.actions]
        mask[-1] = 0  # fixme action info should be removed
        return np.array(mask, dtype=np.int8)

    def _get_obs(self):
        return {
            "field": self._get_field(),
            "stats": self._get_stats(),
        }

    def _get_info(self):
        return {
            "step": self.step_count,
            "turn_info": self.response.get_turn_info(),
            "info": self.response.get_info()
        }

    def reset(self, seed=None, options=None):
        # We need the following line to seed self.np_random
        super().reset(seed=seed)

        self.rules = {}
        self.players = []
        self.turns: list | Generator = []

        self.step_count = 0

        self.response = None

        self._setup_game_local(seed=seed)
        self.game = Game(rules=self.rules)
        field = self.game.field
        for i, player in enumerate(self.players, 1):
            field.spawn_player(*player, turn=i)

        self._make_init_turns()

        observation = self._get_obs()
        info = self._get_info()

        if self.render_mode == "human":
            if self.gui is None:
                self.gui = SpectatorGUI(self.game.field, None, self.metadata["render_fps"])
            self.gui.field = field

        return observation, info

    def step(self, action):
        self.step_count += 1

        reward = 0
        is_running = True
        truncated = False

        act = self._action_space_to_action[action]
        current_player = self.game.get_current_player()
        if act[0] is Acts.swap_treasure and current_player.treasure is None and self.game.get_allowed_abilities(
                current_player).get(Acts.swap_treasure):
            # todo если нет клада в руке и можно его подобрать и действие == подобрать
            reward = self._reward()
        is_running = self._process_turn(*act)

        if self.step_count >= self.max_steps:
            truncated = True

        terminated = not is_running
        if not is_running:
            # todo если выиграл
            reward = self._reward()
        observation = self._get_obs()
        info = self._get_info()
        return observation, reward, terminated, truncated, info

    def _reward(self) -> float:
        """
        Compute the reward to be given upon success
        """
        return 1 - 0.9 * (self.step_count / self.max_steps)

    def render(self):
        if self.render_mode == "human":
            self._render_frame()
        if self.render_mode == "rgb_array":
            return self._render_frame()

    def _render_frame(self):
        if self.render_mode == "human":
            act_pl_abilities = self.game.get_allowed_abilities(self.game.get_current_player())
            self.gui.draw(act_pl_abilities, self.game.get_current_player().name)
            self.gui.get_action({})

    def close(self):
        if self.gui is not None:
            pygame.display.quit()
            pygame.quit()

    def _get_field(self):
        # return encode(self.game.field.game_map, self.game.field.treasures, *self._get_agent_location())
        return encode(self.game.field.game_map, self.game.field.treasures)

    def _get_agent_location(self):
        x, y = self.game.get_current_player().cell.position.get()
        return x, y

    def _get_stats(self):
        player = self.game.get_current_player()
        return np.array(
            [
                player.health, player.arrows, player.bombs, 1 if player.treasure else 0,
                *self._get_agent_location()
            ],
            dtype=np.uint8)
