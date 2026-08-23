class BattleNetError(Exception):
    pass


class InvalidCredentials(BattleNetError):
    pass


class ChallengeRequired(BattleNetError):
    def __init__(self, challenge_type, challenge_id=None):
        super().__init__(f"нужен код ({challenge_type})")
        self.challenge_type = challenge_type
        self.challenge_id = challenge_id
