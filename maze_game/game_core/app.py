"""runs game local for testing game_engine"""
import random
import threading
import time
from typing import Generator
import requests

from maze_game.game_core.GUI import SpectatorGUI
from maze_game.game_core.game_engine import Game, base_rules as ru
from maze_game.game_core.game_engine import Actions, Directions, Position, LevelPosition

from maze_game.game_core.bots_ai.core import BotAI, BotAIDebug
from maze_game.game_core.bots_ai.field_handler.grid import Grid
from maze_game.game_core.bots_ai.decision_making.draw_graph_utils import test_graph


class LocalGame:
    def __init__(
            self, num_players=2, spawn_points: tuple = None, seed: float = None,
            room_id: int = None, server_url: str = '', with_bot=False, save_replay=True
    ):
        self.bot: BotAI | None = None
        self.is_replay = False
        self.turn_number = 0
        self.save_replay = save_replay
        # self.replay_file = open('replay.txt', 'w')
        self.players = []
        self.turns: list | Generator = []
        self.rules = {}
        if room_id is None or server_url == '':
            self.setup_game_local(num_players, spawn_points, seed)
        else:
            self.is_replay = True
            self.setup_game_replay(room_id, server_url)
        self.game = Game(rules=self.rules)
        field = self.game.field
        for i, player in enumerate(self.players, 1):
            field.spawn_player(*player, turn=i)
        if with_bot:
            self._init_bot()

    def setup_game_local(self, num_players: int, spawn_points: tuple | None, seed: float = None):
        self.rules = ru
        # self.rules['generator_rules']['river_rules']['has_river'] = False
        # self.rules['generator_rules']['walls']['has_walls'] = False
        # self.rules['generator_rules']['exits_amount'] = 20
        # self.rules['generator_rules']['rows'] = 6
        # self.rules['generator_rules']['cols'] = 6
        self.rules['generator_rules']['is_separated_armory'] = True
        self.rules['generator_rules']['seed'] = random.random() if seed is None else seed
        # self.rules['generator_rules']['levels_amount'] = 2
        self.rules['gameplay_rules']['fast_win'] = True
        self.rules['gameplay_rules']['diff_outer_concrete_walls'] = True
        # self.rules['generator_rules']['river_rules']['min_coverage'] = 90
        # self.rules['generator_rules']['river_rules']['max_coverage'] = 100

        self.players = self._create_players(num_players, spawn_points)
        self.turns = []

    def _create_players(self, num_players: int, spawn_points: tuple | None):
        random.seed(self.rules.get('generator_rules').get('seed'))
        if spawn_points and len(spawn_points) == num_players:
            return [(spawn_points[i], f'player_{i}') for i, spawn_point in enumerate(spawn_points)]
        return [(self._create_spawn(), f'player_{i}') for i in range(num_players)]

    def _create_spawn(self) -> dict[str, int]:
        return {
            'x': random.randint(1, self.rules.get('generator_rules').get('cols')),
            'y': random.randint(1, self.rules.get('generator_rules').get('rows'))
        }

    def setup_game_replay(self, room_id: int, server_url: str):
        resp = self._get_game_data(room_id, server_url)
        if not resp:
            return
        self.rules = resp.get('rules')
        self.turns = self._get_turn(resp.get('turns'))
        self.players = []
        for player in resp.get('spawn_points'):
            self.players.append((player.get('point'), player.get('name')))

    @staticmethod
    def _get_game_data(room_id: int, server_url: str) -> dict | None:
        try:
            response = requests.get(f'http://{server_url}/api/room_data/{room_id}')
            return response.json()
        except Exception as ex:
            print(ex)
            return

    @staticmethod
    def _get_turn(turns: list):
        for turn in turns:
            yield Actions[turn.get('action')], Directions[turn.get('direction')] if turn.get('direction') else None

    def _init_bot(self):
        players_: dict[str, Position] = {
            player_name: Position(pl_pos.get('x'), pl_pos.get('y')) for pl_pos, player_name in self.players}
        self.bot = BotAIDebug(self.rules, players_)
        self.bot.real_field = self.game.field.game_map.get_level(LevelPosition(0, 0, 0)).field  # todo only for testing

    def run(self, auto=False):
        print('seed:', self.rules['generator_rules']['seed'])
        field = self.game.field
        gui = SpectatorGUI(field, self.bot)

        state = Actions.move
        is_running = True
        for _ in self.players:
            act = (Actions.info, None) if not self.is_replay else next(self.turns)
            is_running, _ = self.process_turn(*act)

        skip_turns = 0
        while is_running:
            act_pl_abilities = self.game.get_allowed_abilities(self.game.get_current_player())
            gui.draw(act_pl_abilities, self.game.get_current_player().name)
            act, state = gui.get_action(act_pl_abilities, state)
            if act or self.turn_number < skip_turns:
                if auto:
                    act = self.bot.make_decision(self.game.get_current_player().name, act_pl_abilities)
                else:
                    act = act if not self.is_replay else next(self.turns)
                is_running, _ = self.process_turn(*act)
        gui.close()

    def run_performance_test(self, verbose=False):
        print('seed:', self.rules['generator_rules']['seed'])

        is_running = True
        for _ in self.players:
            act = (Actions.info, None) if not self.is_replay else next(self.turns)
            is_running, _ = self.process_turn(*act, verbose=verbose)
        step = 0
        times = []
        tr_step = 0
        num_shot = 0
        shot_success = 0
        while is_running:
            act_pl_abilities = self.game.get_allowed_abilities(self.game.get_current_player())
            time_start = time.time()
            act = self.bot.make_decision(self.game.get_current_player().name, act_pl_abilities)

            if tr_step == 0 and act[0] is Actions.swap_treasure:
                tr_step = step
            if act[0] is Actions.shoot_bow:
                num_shot += 1
            is_running, response = self.process_turn(*act, verbose=verbose)
            time_end = time.time() - time_start
            if response.get_raw_info().get('response').get('hit'):
                shot_success += 1
            times.append(time_end)
            step += 1
        return times, step, tr_step, num_shot, shot_success

    def process_turn(self, action: Actions, direction: Directions, verbose=True):
        response, next_player = self.game.make_turn(action.name, direction.name if direction else None)
        if verbose:
            print(self.turn_number, response.get_turn_info(), response.get_info())
        if self.bot:
            self.bot.process_turn_resp(response.get_raw_info())
        self.turn_number += 1
        if self.game.is_win_condition(self.rules):
            return False, response
        return True, response


def draw_graph(grid: Grid, player_cell=None, player_abilities=None):
    gb = test_graph(grid, player_cell, player_abilities)
    # while True:
    #     try:
    #         p1 = Position(*[int(i) for i in input('p1: (x, y):').split(',')])
    #         p2 = Position(*[int(i) for i in input('p2: (x, y):').split(',')])
    #         gb.get_path(grid.get_cell(p1), grid.get_cell(p2))
    #     except Exception:
    #         print('stopped')
    #         break


def main(
        num_players: int = 2, spawn_points: tuple = None, seed: float = None,
        room_id: int = None, server_url: str = '', with_bot: bool = True
):
    game = LocalGame(num_players, spawn_points, seed, room_id, server_url, with_bot)
    start_map = Grid(game.game.field.game_map.get_level(LevelPosition(0, 0, 0)).field)
    current_player = game.game.get_current_player()
    current_player_abilities = game.game.get_allowed_abilities(current_player)
    game.run(auto=True)
    # tr1 = threading.Thread(target=game.run, kwargs={'auto': True})
    # tr2 = threading.Thread(target=draw_graph, args=(start_map, current_player.cell, current_player_abilities))
    # tr1.start()
    # tr2.start()

    # tr1.join()
    # tr2.join()


def performance_test(num_players=2, iters=10, verbose=False):
    all_times = []
    all_steps = []
    all_steps_tr = []
    shots, shoots_s = 0, 0
    for i in range(iters):
        game = LocalGame(num_players=num_players, with_bot=True)
        times, steps, tr_steps, sh, sh_s = game.run_performance_test(verbose)
        all_steps.append(steps)
        all_steps_tr.append(tr_steps)
        all_times.append(times)
        shots += sh
        shoots_s += sh_s
    return {
        'steps': all_steps,
        'tr_steps': all_steps_tr,
        'times': all_times,
        'shooting res': (shots, shoots_s)
    }


if __name__ == "__main__":
    r_id = 43
    s_url = '192.168.1.118:5000'
    _seed = 0.5380936623177652
    _num_players = 4
    _spawn_points = (
        {'x': 5, 'y': 3},
        {'x': 2, 'y': 4},
        {'x': 2, 'y': 1},
        {'x': 3, 'y': 2},
    )
    # main(room_id=r_id, server_url=s_url, with_bot=True)
    main(num_players=_num_players, spawn_points=None, seed=_seed)
    # main(num_players=_num_players, spawn_points=_spawn_points[:_num_players], seed=_seed)
    # res = performance_test(num_players=_num_players, iters=100, verbose=False)
    # print(res)
