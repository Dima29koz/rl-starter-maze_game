import random

import gymnasium
import numpy as np
from gymnasium import spaces

from pettingzoo import AECEnv
from pettingzoo.utils import wrappers
from pettingzoo.utils.agent_selector import agent_selector

from maze_game.game_core import SpectatorGUI, Game, Actions as Acts, Directions
from maze_game.game_core import base_rules as ru
from maze_game.game_core.game_engine.field import wall as w
from maze_game.game_map_encoder import one_hot_encode
from maze_game.multiagent.actions import Actions, action_space_to_action


def create_env(render_mode=None, **kwargs):
    env = MAMazeGameEnv(render_mode=render_mode, **kwargs)
    env = wrappers.TerminateIllegalWrapper(env, illegal_reward=-1)
    env = wrappers.AssertOutOfBoundsWrapper(env)
    env = wrappers.OrderEnforcingWrapper(env)
    return env


class MAMazeGameEnv(AECEnv):
    metadata = {
        "render_modes": ["human", "rgb_array"],
        "name": "maze_game_v2",
        "is_parallelizable": False,
        "render_fps": 2,
    }
    _skip_agent_selection: str
    _agent_selector: agent_selector

    def __init__(self, render_mode=None, size=5, max_steps=250, seed=None, num_players=1):
        super().__init__()
        self.size = size
        self.max_steps = max_steps
        self.render_mode = render_mode

        self.agents = [f"player_{i}" for i in range(num_players)]
        self.possible_agents = self.agents[:]

        self.gui: SpectatorGUI | None = None
        self.game = None
        self.rules = {}
        self.players = []
        self.step_count = 0

        self.reset(seed)

        self.action_spaces = {i: spaces.Discrete(len(Actions)) for i in self.agents}

        field_observation_space = spaces.Box(
            low=0,
            high=1,
            shape=(13, self.size + 2, self.size + 2),
            dtype=np.uint8,
        )
        walls_observation_space = spaces.Box(
            low=0,
            high=1,
            shape=(12, 4, self.size + 2, self.size + 2),
            dtype=np.uint8,
        )
        treasures_observation_space = spaces.Box(
            low=0,
            high=2,
            shape=(1, self.size + 2, self.size + 2),
            dtype=np.uint8,
        )

        self.observation_spaces = {
            i: spaces.Dict(
                {
                    "field": field_observation_space,
                    "walls": walls_observation_space,
                    "treasures": treasures_observation_space,
                    "stats": spaces.Box(0, 7, shape=(6, 4), dtype=np.float32),
                    "action_mask": spaces.Box(low=0, high=1, shape=(len(Actions),), dtype=np.int8),
                }
            )
            for i in self.agents
        }

    def _setup_game_local(self, seed=None):
        self.rules = ru
        # self.rules['generator_rules']['river_rules']['has_river'] = False
        # self.rules['generator_rules']['walls']['has_walls'] = False
        self.rules['generator_rules']['rows'] = self.size
        self.rules['generator_rules']['cols'] = self.size
        self.rules['generator_rules']['is_separated_armory'] = True
        self.rules['generator_rules']['seed'] = random.random() if seed is None else seed
        # self.rules['gameplay_rules']['fast_win'] = False
        self.rules['gameplay_rules']['diff_outer_concrete_walls'] = True

    def _create_players(self):
        return [(self._create_spawn(), agent) for agent in self.agents]

    def _create_spawn(self) -> dict[str, int]:
        return {'x': random.randint(1, self.size), 'y': random.randint(1, self.size)}

    def _make_init_turns(self):
        for _ in self.players:
            self._process_turn(Acts.info, None)

    def _process_turn(self, action: Acts, direction: Directions | None):
        response, next_player = self.game.make_turn(action.name, direction.name if direction else None)
        if response is not None:
            self.infos[self.agent_selection] = {
                'turn_info': response.get_turn_info(),
                'resp': response.get_info(),
            }
            dead_agents = response.get_raw_info().get('response', {}).get('dead_pls', [])
            for agent in dead_agents:
                self.truncations[agent] = True
        if self.game.is_win_condition(self.rules):
            return False
        if action is not Acts.swap_treasure:
            self.agent_selection = self._agent_selector.next()
        return True

    def _action_masks(self, agent):
        mask = np.zeros(len(Actions), np.int8)
        if agent != self.agent_selection:
            return mask

        current_player = self.game.get_current_player()
        act_pl_abilities = self.game.get_allowed_abilities(current_player)

        mask[0] = act_pl_abilities.get(Acts.swap_treasure)
        for i, direction in enumerate(Directions, 1):
            wall = current_player.cell.walls[direction]
            mask[i] = not wall.player_collision
            if act_pl_abilities.get(Acts.throw_bomb):
                mask[4 + i] = wall.breakable and type(wall) is not w.WallEmpty

            if act_pl_abilities.get(Acts.shoot_bow):
                mask[8 + i] = not wall.weapon_collision

        return mask

    def _get_obs(self):
        return one_hot_encode(self.game.field.game_map, self.game.field.treasures)

    def _get_stats(self):
        player = self.game.get_current_player()
        return np.array(
            [
                player.health / player.health_max,
                player.arrows / player.arrows_max,
                player.bombs / player.bombs_max,
                1 if player.treasure else 0,
                *self._get_agent_location()
            ],
            dtype=np.float32)

    def _get_agent_location(self):
        x, y = self.game.get_current_player().cell.position.get()
        return x, y

    def _reward(self) -> float:
        return 1 - 0.9 * (self.step_count / self.max_steps)

    def observe(self, agent):
        field, walls, treasures = self._get_obs()

        return {
            "field": field,
            "walls": walls,
            "treasures": treasures,
            "stats": self._get_stats(),
            "action_mask": self._action_masks(agent),
        }

    def observation_space(self, agent):
        return self.observation_spaces[agent]

    def action_space(self, agent):
        return self.action_spaces[agent]

    def step(self, action):
        self.step_count += 1
        current_agent = self.agent_selection
        if (
                self.truncations[current_agent]
                or self.terminations[current_agent]
        ):
            self._skip_agent_selection = self._agent_selector.next()
            return self._was_dead_step(action)
        # assert valid move
        current_player = self.game.get_current_player()
        act = action_space_to_action(action)
        assert self.game.get_allowed_abilities(current_player).get(act[0]) is True, "played illegal move."

        if act[0] is Acts.swap_treasure and current_player.treasure is None:
            self.rewards[current_agent] = self._reward()
        is_running = self._process_turn(*act)

        # check if there is a winner
        if not is_running:
            reward = self._reward()
            self.rewards[current_agent] = reward
            for agent in self.agents:
                if agent != current_agent:
                    self.rewards[agent] = -reward
            self.terminations = {i: True for i in self.agents}

        self._accumulate_rewards()

    def reset(self, seed=None, options=None):
        # reset environment
        self.step_count = 0

        self.agents = self.possible_agents[:]
        self.rewards = {i: 0 for i in self.agents}
        self._cumulative_rewards = {name: 0 for name in self.agents}
        self.terminations = {i: False for i in self.agents}
        self.truncations = {i: False for i in self.agents}
        self.infos = {i: {} for i in self.agents}

        self._agent_selector = agent_selector(self.agents)

        self.agent_selection = self._agent_selector.reset()

        self._setup_game_local(seed=seed)
        self.players = self._create_players()
        self.game = Game(rules=self.rules)
        for i, player in enumerate(self.players, 1):
            self.game.field.spawn_player(*player, turn=i)

        self._make_init_turns()

    def render(self):
        if self.render_mode is None:
            gymnasium.logger.warn("You are calling render method without specifying any render mode.")
            return

        if self.render_mode == "human":
            if self.gui is None:
                self.gui = SpectatorGUI(self.game.field, None, self.metadata["render_fps"])
            self.gui.field = self.game.field

        if self.render_mode == "human":
            act_pl_abilities = self.game.get_allowed_abilities(self.game.get_current_player())
            self.gui.draw(act_pl_abilities, self.game.get_current_player().name)
            self.gui.get_action(act_pl_abilities)

    def close(self):
        if self.gui is not None:
            import pygame
            pygame.display.quit()
            pygame.quit()
            self.gui = None