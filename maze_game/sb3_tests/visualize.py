import gymnasium as gym
from stable_baselines3 import PPO

from maze_game import MazeGameEnv

env = gym.make('env_maze/MazeGame-v0', render_mode='human')
model = PPO.load("storage/ppo_MazeGame", env=env)

sum_reward = 0
eps = 0
wins = 0
for episode in range(10_000):
    obs, info = env.reset()
    eps += 1
    while True:
        action, _states = model.predict(obs)
        obs, reward, terminated, truncated, info = env.step(int(action))
        print(info)
        env.render()
        done = terminated | truncated
        if terminated:
            wins += 1
            sum_reward += reward

        if done or env.gui is None:
            break
    print(f"eps={eps}, mean-rew={sum_reward/eps}, wins={wins}")
    if env.gui is None:
        break