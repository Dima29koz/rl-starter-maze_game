"""
Example from
https://github.com/DLR-RM/stable-baselines3/tree/feat/gymnasium-support
requires:
pip install git+https://github.com/DLR-RM/stable-baselines3@feat/gymnasium-support
pip install git+https://github.com/Stable-Baselines-Team/stable-baselines3-contrib@feat/gymnasium-support
"""

import gymnasium as gym

from stable_baselines3 import PPO

env = gym.make("CartPole-v1")

model = PPO("MlpPolicy", env, verbose=1)
model.learn(total_timesteps=10_000)

vec_env = model.get_env()
vec_env.envs[0].unwrapped.render_mode = 'human'
obs = vec_env.reset()
for i in range(1000):
    action, _states = model.predict(obs, deterministic=True)
    obs, reward, done, info = vec_env.step(action)
    vec_env.render(mode='human')
    # VecEnv resets automatically
    # if done:
    #   obs = env.reset()

env.close()