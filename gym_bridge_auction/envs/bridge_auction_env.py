import random
import time
import numpy as np
import gym
from gym import error
from gym import spaces
from gym_bridge_auction.envs.solver_results import *
from gym_bridge_auction.envs.dynamic_space import Dynamic
from gym_bridge_auction.envs.render import Window


class AuctionEnv(gym.Env):
    """Środowisko wieloagentowe (czterech graczy) symulujące licytację brydżową."""

    metadata = {'render.modes': ['human', 'console'], 'video.frames_per_second': 1}

    def __init__(self):

        self._win = None  # instancja interfejsu graficznego
        self.viewer = None  # zmienna pomocnicza do renderowania
        self.n_players = 4  # liczba graczy
        self.deck = Deck()  # utworzenie talii
        self.players = []  # lista graczy
        self.reward_range = (-9280, 9280)
        # przestrzeń obserwacji
        self.observation_space = spaces.Dict({'whose turn': spaces.Discrete(self.n_players),
                                              'whose next turn': spaces.Discrete(self.n_players),
                                              'LAST_contract': spaces.Discrete(36),
                                              'NORTH_contract': spaces.Discrete(36),
                                              'EAST_contract': spaces.Discrete(36),
                                              'SOUTH_contract': spaces.Discrete(36),
                                              'WEST_contract': spaces.Discrete(36),
                                              'winning_pair': spaces.Discrete(self.n_players / 2),
                                              'double/redouble': spaces.Discrete(3),
                                              'Players hand': spaces.Tuple(
                                                  [spaces.MultiDiscrete([2 for _ in range(0, len(self.deck.deck))])
                                                   for _ in range(0, self.n_players)]),
                                              'pair score/optimum score': spaces.Box(low=-7000, high=7000, shape=(4,),
                                                                                     dtype=np.int32)})
        self.action_space = Dynamic(38)  # przestrzeń dostępnych działań agenta

        self.dealer_name = ''  # Nazwa gracza, który to rozdający
        self.index_order = None  # indeks aktualnie licytującego gracza (z listy graczy w odpowiedniej kolejności)
        self.players_order = []  # lista graczy ustawionych w odpowiedniej kolejności licytowania
        self.last_contract = None  # ustalony kontrakt
        self.first_bind_pass = False  # czy pierwsza odzywka była pasem

        # Utworzenie dostępnych kontraktów (lista obiektów typu Contract)
        self.available_contracts = self.create_available_contracts()
        self.deck.shuffle()  # tasowanie talii
        _hands = self.deck.deal(self.n_players)  # rozdanie kart dla graczy
        self.players = [Player(NAMES[i], _hands[i]) for i in range(0, self.n_players)]  # utworzenie listy graczy

        # rozdzielenie rąk graczy ze względu na kolor karty (w każdym wierszu figury/numery w danym kolorze)
        for j in range(0, len(self.players)):
            self.players[j].split_hand()
            for i in range(0, 4):
                self.players[j].hand_splitted[i] = self.players[j].hand_to_display(self.players[j].hand_splitted[i])

        self.choose_dealer_and_order()  # wybór rozdającego i kolejność licytacji
        self.reward = [None, None]
        self.pass_number = 0
        self.optimum_contract_score = [None, None]  # optymalne punkty z solvera
        self.score = [0, 0]  # zapis dla danych par
        self.insert_solver_results()  # wstawienie wyników z solvera dla poszczególnych graczy
        self.double = False  # czy była kontra
        self.redouble = False  # czy była rekontra
        self.max_contract = None
        self.max_number_of_tricks = None
        self.reset()

    def step(self, action):
        assert self.action_space.contains(action), "%r (%s) invalid" % (action, type(action))

        state = self.get_game_state(action, False)
        self.reward = self.get_reward(state, action)
        state['pair score/optimum score'] = np.array([self.optimum_contract_score[0], self.optimum_contract_score[1],
                                                      self.score[0], self.score[1]])
        self.index_order += 1

        if self.index_order == 4:
            self.index_order = 0
        done = self.is_over(action)

        # wyznaczenie dostępnych działań z przestrzeni akcji
        self.action_space.set_available_actions(action, state)

        return state, self.reward, done, {}

    def reset(self):
        self.reward = [None, None]
        self.score = [0, 0]
        self.max_number_of_tricks = None
        self.max_contract = None
        self.viewer = None
        self.pass_number = 0
        self.index_order = 0
        self.first_bind_pass = False
        self.double = False
        self.redouble = False
        self.action_space.new_n = 36
        self.action_space.available_actions = list(range(0, 36))
        return self.get_game_state(None, True)

    def render(self, mode='console'):

        if mode == 'human':

            if self.viewer is None:
                self._win = Window(self.players[0].hand_splitted, self.players[1].hand_splitted,
                                   self.players[2].hand_splitted, self.players[3].hand_splitted, self.dealer_name)
                self.viewer = True

            else:
                if self.double:
                    last_contract = self.last_contract.__str__() + 'X'
                elif self.redouble:
                    last_contract = self.last_contract.__str__() + 'XX'
                else:
                    last_contract = self.last_contract.__str__()
                self._win.update_view(last_contract, self.players[0].player_contracts.__str__(),
                                      self.players[1].player_contracts.__str__(),
                                      self.players[2].player_contracts.__str__(),
                                      self.players[3].player_contracts.__str__(),
                                      PAIR,
                                      self.score,
                                      self.optimum_contract_score,
                                      self.metadata['video.frames_per_second'])

            time.sleep(2)
        elif mode == 'console':
            if self.viewer is None:
                print('Dealer: ' + self.dealer_name)

                for i in range(0, self.n_players):
                    print(' ')
                    print(self.players[i].name + ' hand:')
                    print(spade + ' ' + self.players[i].hand_splitted[0])
                    print(heart + ' ' + self.players[i].hand_splitted[1])
                    print(diamond + ' ' + self.players[i].hand_splitted[2])
                    print(club + ' ' + self.players[i].hand_splitted[3])

                print(' ')

                self.viewer = False

            else:
                print('')
                if self.double:
                    print('LAST_contract: ' + self.last_contract.__str__() + ' X')
                elif self.redouble:
                    print('LAST_contract: ' + self.last_contract.__str__() + ' XX')
                else:
                    print('LAST_contract: ' + self.last_contract.__str__())

                print('Pair: ' + PAIR[0] + '  ' + PAIR[1])

                print('Score: ' + str(self.score[0]) + '  ' + str(self.score[1]))
                print('Optimum score: ' + str(self.optimum_contract_score[0]) + '  ' +
                      str(self.optimum_contract_score[1]))
                print(' ')

                print('NORTH_contract: ' + self.players[0].player_contracts.__str__())
                print('EAST_contract: ' + self.players[1].player_contracts.__str__())
                print('SOUTH_contract: ' + self.players[2].player_contracts.__str__())
                print('WEST_contract: ' + self.players[3].player_contracts.__str__())
                print(' ')

        else:
            raise error.UnsupportedMode('Unsupported render mode' + mode)

    def close(self):
        if self.viewer is True:
            # jak mode == 'human'
            self.viewer = None
            self._win.close_window()
        elif self.viewer is False:
            # jak mode == 'console'
            self.viewer = None
        else:
            self.viewer = None

    def pbn_deal_representation(self):
        """Dane rozdanie w formacie PBN"""

        pbn = ""
        pbn += self.dealer_name
        pbn += ':'

        for j in range(0, self.n_players):

            for i in range(0, 4):
                list_pom = self.players[j].hand_splitted[i].split()
                # list_pom.reverse()

                for k in list_pom:
                    if k == '10':
                        pbn += 'T'
                    else:
                        pbn += k

                if i < 3:
                    pbn += '.'

            if j < 3:
                pbn += " "

        return pbn

    def insert_solver_results(self):
        """Metoda przypisująca wszystkim graczom odpowiednie rezultaty o ilości wziętych lew i maksymalnych możliwych
        kontraktach otrzymanych z Dummy Double Solver"""

        pbn_repr = self.pbn_deal_representation()
        solver_results = get_results_from_solver(pbn_repr)

        for i in range(0, self.n_players):
            self.players[i].number_of_trick = get_solver_result_for_player(i, solver_results)
            self.players[i].makeable_contracts = max_contract_for_suit(self.players[i].number_of_trick)

        self.optimum_contract_score[0] = get_optimum_contracts_from_solver(pbn_repr,
                                                                           self.players.index(self.players_order[0]))
        self.optimum_contract_score[1] = - self.optimum_contract_score[0]
        # points_for_contracts = calc_point_for_contract(self.players[i].makeable_contracts)
        # self.players[i].max_contract_score = choose_best_contracts(points_for_contracts)

    @staticmethod
    def create_available_contracts():
        """Utworzenie dostępnych kontraktów podczas licytacji"""

        numbers = [1, 2, 3, 4, 5, 6, 7]
        contracts = [Contract(i, j) for j in numbers for i in BIND_SUIT]
        contracts.reverse()
        contracts.insert(0, Contract('pass', None))
        contracts.append(Contract('double', None))
        contracts.append(Contract('redouble', None))

        for i in range(0, len(contracts)):
            contracts[i].value = i

        return contracts

    def choose_dealer_and_order(self):
        """Wybór rozdającego oraz ustalenie kolejności licytacji"""

        dealer = random.choice(range(len(self.players)))
        # self.players[dealer].is_dealer = True
        self.dealer_name = self.players[dealer].name
        self.index_order = 0
        self.players_order.append(self.players[dealer])

        if dealer < len(self.players) - 1:
            for i in range(dealer + 1, len(self.players)):
                self.players_order.append(self.players[i])
        if dealer > 0:
            for i in range(0, dealer):
                self.players_order.append(self.players[i])

    def get_game_state(self, action, reset):
        """Wyznaczenie przestrzeni obserwacji"""

        state = {}

        # przestrzeń obserwacji dla funkcji reset
        if reset:
            for i in range(0, len(self.players)):
                self.players[i].player_contracts = None
                self.players[i].win_auction = False

            state['whose turn'] = None
            state['whose next turn'] = self.players.index(self.players_order[0])
            state['LAST_contract'] = None
            state['NORTH_contract'] = None
            state['EAST_contract'] = None
            state['SOUTH_contract'] = None
            state['WEST_contract'] = None
            state['winning_pair'] = None
            state['double/redouble'] = 0
            self.last_contract = None
            state['Players hand'] = [[] for _ in range(0, self.n_players)]
            state['pair score/optimum score'] = np.array([self.optimum_contract_score[0], self.optimum_contract_score[1],
                                                          self.score[0], self.score[1]])

            for player in enumerate(self.players):
                state['Players hand'][player[0]] = player[1].hand_representation

        else:

            player_index = self.players.index(self.players_order[self.index_order])
            state['whose turn'] = player_index

            if player_index == 3:
                state['whose next turn'] = 0
            else:
                state['whose next turn'] = player_index + 1

            if self.last_contract is None:
                # jak jest początek licytacji
                state['LAST_contract'] = action
                self.last_contract = self.available_contracts[action]
                state['double/redouble'] = 0
                if action == 0:
                    self.first_bind_pass = True
                    self.players[player_index].win_auction = False
                else:
                    self.players[player_index].win_auction = True

            elif (action < self.last_contract.value or self.last_contract.value == 0) and action != 0:
                #  jeśli działanie to nie kontra/rekontra/pas lub wszycy gracze od początku licytacji spasowali
                #  i obecne działanie nie jest pasem

                state['LAST_contract'] = action
                self.last_contract = self.available_contracts[action]
                self.first_bind_pass = False

                for i in range(0, len(self.players)):
                    self.players[i].win_auction = False

                self.players[player_index].win_auction = True

                # nowy kontrakt kasuje kontrę lub rekontrę
                state['double/redouble'] = 0
                self.redouble = False
                self.double = False

            else:
                # jeśli działanie to kontra/rekontra/pas
                state['LAST_contract'] = self.last_contract.value

                if action == 36:
                    # jeśli kontra
                    state['double/redouble'] = 1
                    self.double = True
                    self.first_bind_pass = False
                elif action == 37:
                    # jeśli rekontra
                    state['double/redouble'] = 2
                    self.redouble = True
                    self.double = False
                    self.first_bind_pass = False
                else:
                    if self.double:
                        state['double/redouble'] = 1
                    elif self.redouble:
                        state['double/redouble'] = 2
                    else:
                        state['double/redouble'] = 0

            self.players[player_index].player_contracts = self.available_contracts[action]

            for player in self.players:
                if player.win_auction is True:
                    if self.players.index(player) in WIN_PAIR[0]:
                        state['winning_pair'] = 0
                    elif self.players.index(player) in WIN_PAIR[1]:
                        state['winning_pair'] = 1

            if state['LAST_contract'] == 0:
                state['winning_pair'] = None

            if player_index == 0:
                state['NORTH_contract'] = action
            elif player_index == 1:
                state['EAST_contract'] = action
            elif player_index == 2:
                state['SOUTH_contract'] = action
            elif player_index == 3:
                state['WEST_contract'] = action

        return state

    def get_reward(self, state, action):
        """Wyznaczenie nagrody za wykonane działanie przez poszczególnego agenta"""

        reward = [None, None]

        if self.last_contract.value == 0:
            # przypadek gdy na początku licytacji (lub ewentualnie w dalszych krokach) zgłoszono pas
            # - nie ustalono kontraktu
            self.score = [0, 0]
            reward[0] = self.score[0] - self.optimum_contract_score[0]
            reward[1] = - reward[0]

        else:
            # ustalono jakiś kontrakt

            ind_w = state['winning_pair']  # indeks pary z najwyższym zgłoszonym kontraktem
            ind_o = None  # indeks pary przeciwnej

            for i in enumerate(WIN_PAIR):
                if i[0] != ind_w:
                    ind_o = i[0]

            optimum_contract_score = self.optimum_contract_score[ind_w]

            if action == 0:  # działanie agenta to pas
                reward = self.reward

            else:
                # działanie agenta to odzywka licytacyjna lub kontra/rekontra
                bind_trump = self.last_contract.suit
                bind_number = self.last_contract.number

                if action != 36 and action != 37:
                    self.max_contract = self.players[state['whose turn']].makeable_contracts[bind_trump]
                    self.max_number_of_tricks = self.players[state['whose turn']].number_of_trick[bind_trump]

                number_of_tricks = bind_number + 6
                trick_difference = number_of_tricks - self.max_number_of_tricks

                if bind_number <= self.max_contract:
                    # kontrakt jest realizowalny
                    # punkty za lewy
                    if bind_trump == 'NT':
                        self.score[ind_w] = CONTRACT_POINTS['NT'][0] + (bind_number - 1) * CONTRACT_POINTS['NT'][1]
                    else:
                        self.score[ind_w] = bind_number * CONTRACT_POINTS[bind_trump]

                    # punkty za kontrę lub rekontrę plus premie
                    if state['double/redouble'] == 1:
                        # kontra
                        self.score[ind_w] *= CONTRACT_POINTS['X']
                        self.score[ind_w] += BONUS['DOUBLE']

                    elif state['double/redouble'] == 2:
                        self.score[ind_w] *= CONTRACT_POINTS['XX']
                        self.score[ind_w] += BONUS['REDOUBLE']

                    # premie za częściówki, dograne
                    if self.score[ind_w] < 100:
                        self.score[ind_w] += BONUS['PARTIAL-GAME']
                    else:
                        self.score[ind_w] += BONUS['GAME']

                    # premie szlemiki, szlemy
                    if bind_number == 6:
                        self.score[ind_w] += BONUS['SLAM']
                    elif bind_number == 7:
                        self.score[ind_w] += BONUS['GRAND_SLAM']

                    # premie za nadróbki
                    if bind_number != self.max_contract:
                        if state['double/redouble'] == 0:
                            if bind_trump == 'NT':
                                self.score[ind_w] += CONTRACT_POINTS['NT'][1] * (self.max_contract - bind_number)
                            else:
                                self.score[ind_w] += CONTRACT_POINTS[bind_trump] * (self.max_contract - bind_number)
                        elif state['double/redouble'] == 1:
                            self.score[ind_w] += BONUS['OVERTRICKS_DOUBLE'] * (self.max_contract - bind_number)
                        elif state['double/redouble'] == 2:
                            self.score[ind_w] += BONUS['OVERTRICKS_REDOUBLE'] * (self.max_contract - bind_number)

                    self.score[ind_o] = -self.score[ind_w]
                    reward[ind_w] = self.score[ind_w] - optimum_contract_score
                    reward[ind_o] = -reward[ind_w]
                else:
                    # kontrakt nie jest realizowalny
                    if state['double/redouble'] == 0:
                        # nie było kontry lub rekontry
                        self.score[ind_o] = PENALTY_POINTS['NO DOUBLE/REDOUBLE'] * trick_difference
                    elif state['double/redouble'] == 1:
                        self.score[ind_o] = PENALTY_POINTS['DOUBLE'][0] + \
                                            PENALTY_POINTS['DOUBLE'][0] * PENALTY_POINTS['DOUBLE'][1] * \
                                            (trick_difference - 1)
                        if trick_difference >= 4:
                            self.score[ind_o] += PENALTY_POINTS['DOUBLE'][0] * (trick_difference - 3)
                    elif state['double/redouble'] == 2:
                        self.score[ind_o] = PENALTY_POINTS['REDOUBLE'][0] + \
                                            PENALTY_POINTS['REDOUBLE'][0] * PENALTY_POINTS['REDOUBLE'][1] \
                                            * (trick_difference - 1)
                        if trick_difference >= 4:
                            self.score[ind_o] += PENALTY_POINTS['REDOUBLE'][0] * (trick_difference - 3)

                    self.score[ind_w] = -self.score[ind_o]
                    reward[ind_w] = self.score[ind_w] - optimum_contract_score
                    reward[ind_o] = - reward[ind_w]

        return reward

    def is_over(self, action):
        """Wyznaczenie warunku końca licytacji"""

        if action == 0:
            self.pass_number += 1
        else:
            self.pass_number = 0

        if self.pass_number == 3 and (not self.first_bind_pass):
            # Jak 3 graczy spasuje po ustalonym kontrakcie
            return True
        elif self.first_bind_pass and self.pass_number == 4:
            # Jak nie ustalono kontraktu - na początku licytacji wszyscy gracze spasowali
            return True
        elif self.last_contract.value == 1 and self.redouble:
            # Jak ostateczny kontrakt to 7NT a po tym nastąpiła kontra i rekontra
            return True
        else:
            return False
