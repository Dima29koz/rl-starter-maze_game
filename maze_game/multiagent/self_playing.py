import numpy as np
from ray.rllib.algorithms.callbacks import DefaultCallbacks
from ray.rllib.core.rl_module.rl_module import SingleAgentRLModuleSpec


class SelfPlayCallback(DefaultCallbacks):
    def __init__(self):
        super().__init__()
        # 0=RandomPolicy, 1=1st main policy snapshot,
        # 2=2nd main policy snapshot, etc..
        self.current_opponent = 0
        self.current_opponent_policy = 'random'

    def on_train_result(self, *, algorithm, result, **kwargs):
        # Get the win rate for the train batch.
        # Note that normally, one should set up a proper evaluation config,
        # such that evaluation always happens on the already updated policy,
        # instead of on the already used train_batch.
        main_rew = result["hist_stats"].get("policy_main_reward")
        opponent_rew = result["hist_stats"].get(f"policy_{self.current_opponent_policy}_reward", [])
        if not len(main_rew) == len(opponent_rew):
            opponent_rew = [a - b for a, b in zip(
                result['hist_stats'].get('episode_reward'),
                result['hist_stats'].get('policy_main_reward')
            )]
        assert len(main_rew) == len(opponent_rew)
        won = 0
        for r_main, r_opponent in zip(main_rew, opponent_rew):
            if r_main > r_opponent:
                won += 1
        win_rate = won / len(main_rew)
        result["win_rate"] = win_rate

        # If win rate is good -> Snapshot current policy and play against
        # it next, keeping the snapshot fixed and only improving the "main"
        # policy.
        if win_rate > 0.8:
            self.current_opponent += 1
            self.current_opponent_policy = f"main_v{self.current_opponent}"
            new_pol_id = self.current_opponent_policy
            print(f"Iter={algorithm.iteration} win-rate={win_rate} -> ", end="")
            print(f"adding new opponent to the mix ({new_pol_id}).")

            # Re-define the mapping function, such that "main" is forced
            # to play against any of the previously played policies
            # (excluding "random").
            def policy_mapping_fn(agent_id, episode, worker, **kwargs):
                # agent_id = [0|1] -> policy depends on episode ID
                # This way, we make sure that both policies sometimes play
                # (start player) and sometimes agent1 (player to move 2nd).
                agent_id = int(agent_id[-1])
                return (
                    "main"
                    if episode.episode_id % 2 == agent_id
                    else self.current_opponent_policy
                )

            main_policy = algorithm.get_policy("main")
            if algorithm.config._enable_learner_api:
                new_policy = algorithm.add_policy(
                    policy_id=new_pol_id,
                    policy_cls=type(main_policy),
                    policy_mapping_fn=policy_mapping_fn,
                    module_spec=SingleAgentRLModuleSpec.from_module(main_policy.model),
                )
            else:
                new_policy = algorithm.add_policy(
                    policy_id=new_pol_id,
                    policy_cls=type(main_policy),
                    policy_mapping_fn=policy_mapping_fn,
                )

            # Set the weights of the new policy to the main policy.
            # We'll keep training the main policy, whereas `new_pol_id` will
            # remain fixed.
            main_state = main_policy.get_state()
            new_policy.set_state(main_state)
            # We need to sync the just copied local weights (from main policy)
            # to all the remote workers as well.
            algorithm.workers.sync_weights()

        # +2 = main + random
        result["league_size"] = self.current_opponent + 2