import gym
import torch
import random
import numpy as np
from tqdm import tqdm
import torch.nn as nn
import torch.nn.functional as F
import matplotlib.pyplot as plt
from stable_baselines3.common.atari_wrappers import MaxAndSkipEnv
from stable_baselines3.common.buffers import ReplayBuffer


class DQN(nn.Module):
    def __init__(self, nb_actions):
        super().__init__()
        self.network = nn.Sequential(nn.Conv2d(4, 32, 8, stride=4), nn.ReLU(),
                                     nn.Conv2d(32, 64, 4, stride=2), nn.ReLU(),
                                     nn.Conv2d(64, 64, 3, stride=1), nn.ReLU(),
                                     nn.Flatten(), nn.Linear(3136, 512), nn.ReLU(),
                                     nn.Linear(512, nb_actions),)

    def forward(self, x):
        return self.network(x / 255.)


def Deep_Q_Learning(env, buffer_size=1_000_000, nb_epochs=30_000_000, train_frequency=4, batch_size=32,
                    gamma=0.99, replay_start_size=50_000, epsilon_start=1, epsilon_end=0.1,
                    exploration_steps=1_000_000, device='cuda', C=10_000):
    # Initialize replay memory D to capacity N
    rb = ReplayBuffer(buffer_size, env.observation_space, env.action_space, device,
                      optimize_memory_usage=True, handle_timeout_termination=False)

    # Initialize action-value function Q with random weights
    q_network = DQN(env.action_space.n).to(device)
    # Initialize target action-value function Q_hat
    target_network = DQN(env.action_space.n).to(device)
    target_network.load_state_dict(q_network.state_dict())

    optimizer = torch.optim.Adam(q_network.parameters(), lr=1.25e-4)

    epoch = 0
    smoothed_rewards = []
    rewards = []
    best_reward = 0

    progress_bar = tqdm(total=nb_epochs)
    while epoch <= nb_epochs:

        dead = False
        total_rewards = 0

        # Initialise sequence s1 = {x1} and preprocessed sequenced φ1 = φ(s1)
        obs = env.reset()

        for _ in range(random.randint(1, 30)):  # Noop and fire to reset environment
            obs, _, _, info = env.step(1)

        while not dead:
            current_life = info['lives']

            epsilon = max((epsilon_end - epsilon_start) / exploration_steps * epoch + epsilon_start, epsilon_end)
            if random.random() < epsilon:  # With probability ε select a random action a
                action = np.array(env.action_space.sample())
            else:  # Otherwise select a = max_a Q∗(φ(st), a; θ)
                q_values = q_network(torch.Tensor(obs).unsqueeze(0).to(device))
                action = torch.argmax(q_values, dim=1).item()

            # Execute action a in emulator and observe reward rt and image xt+1
            next_obs, reward, dead, info = env.step(action)

            done = True if (info['lives'] < current_life) else False

            # Set st+1 = st, at, xt+1 and preprocess φt+1 = φ(st+1)
            real_next_obs = next_obs.copy()

            total_rewards += reward
            reward = np.sign(reward)  # Reward clipping

            # Store transition (φt, at, rt, φt+1) in D
            rb.add(obs, real_next_obs, action, reward, done, info)

            obs = next_obs

            if epoch > replay_start_size and epoch % train_frequency == 0:
                # Sample random minibatch of transitions (φj , aj , rj , φj +1 ) from D
                data = rb.sample(batch_size)
                with torch.no_grad():
                    max_target_q_value, _ = target_network(data.next_observations).max(dim=1)
                    y = data.rewards.flatten() + gamma * max_target_q_value * (1 - data.dones.flatten())
                current_q_value = q_network(data.observations).gather(1, data.actions).squeeze()
                loss = F.huber_loss(y, current_q_value)

                # Perform a gradient descent step according to equation 3
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            # Every C steps reset Q_hat=Q
            if epoch % C == 0:
                target_network.load_state_dict(q_network.state_dict())

            epoch += 1
            if (epoch % 50_000 == 0) and epoch > 0:
                smoothed_rewards.append(np.mean(rewards))
                rewards = []
                plt.plot(smoothed_rewards)
                plt.title("Average Reward on Breakout")
                plt.xlabel("Training Epochs")
                plt.ylabel("Average Reward per Episode")
                plt.savefig('Imgs/average_reward_on_breakout.png')
                plt.close()

            progress_bar.update(1)
        rewards.append(total_rewards)

        if total_rewards > best_reward:
            best_reward = total_rewards
            torch.save(q_network.cpu(), f'best_model_{best_reward}')
            q_network.to(device)


if __name__ == "__main__":

    env = gym.make("BreakoutNoFrameskip-v4")
    env = gym.wrappers.RecordEpisodeStatistics(env)
    env = gym.wrappers.ResizeObservation(env, (84, 84))
    env = gym.wrappers.GrayScaleObservation(env)
    env = gym.wrappers.FrameStack(env, 4)
    env = MaxAndSkipEnv(env, skip=4)

    Deep_Q_Learning(env, device='cuda')
    env.close()
