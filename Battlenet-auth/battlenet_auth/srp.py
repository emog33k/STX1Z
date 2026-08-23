import hashlib
import secrets


def _sha256(data):
    return hashlib.sha256(data).digest()


def _int_to_hex(n):
    return "0" if n == 0 else format(n, "x")


def _pad_hex(n, length):
    h = format(n, "x")
    return "0" * (length - len(h)) + h if len(h) < length else h


def _to_byte_array(n):
    if n == 0:
        return b"\x00"
    return n.to_bytes(n.bit_length() // 8 + 1, "big")


def compute_x_v1(salt_hex, username, password):
    inner = f"{username}:{password[:16].upper()}".encode()
    digest = _sha256(bytes.fromhex(salt_hex) + _sha256(inner))
    return int.from_bytes(digest, "little")


def compute_x_v2(salt_hex, username, password, iterations):
    inner = f"{username}:{password[:128]}".encode()
    dk = hashlib.pbkdf2_hmac(
        "sha512", inner, bytes.fromhex(salt_hex), iterations, dklen=64
    )
    return int.from_bytes(dk, "big", signed=True)


class SrpProof:
    def __init__(self, public_A_hex, client_evidence_M1_hex):
        self.public_A_hex = public_A_hex
        self.client_evidence_M1_hex = client_evidence_M1_hex


class SrpClient:
    def __init__(self, modulus_hex, generator_hex, version, iterations):
        self.N = int(modulus_hex, 16)
        self.g = int(generator_hex, 16)
        self.version = int(version)
        self.iterations = int(iterations)
        self.pad_len = self.N.bit_length() // 4

    def _modpow(self, base, exp, mod):
        base %= mod
        if exp < 0:
            return pow(pow(base, -exp, mod), -1, mod)
        return pow(base, exp, mod)

    def _pair_hash(self, x1, x2):
        return int.from_bytes(
            _sha256(
                bytes.fromhex(_pad_hex(x1, self.pad_len) + _pad_hex(x2, self.pad_len))
            ),
            "big",
        )

    def _random_private_a(self):
        lower = 1 << (min(256, self.N.bit_length() // 2) - 1)
        return secrets.randbelow(self.N - 1 - lower) + lower

    def _compute_x(self, username, password, salt_hex):
        if self.version == 1:
            return compute_x_v1(salt_hex, username, password)
        return compute_x_v2(salt_hex, username, password, self.iterations)

    def prove(self, username, password, salt_hex, public_B_hex):
        N, g = self.N, self.g
        B = int(public_B_hex, 16)
        if B % N == 0:
            raise ValueError("плохой B от сервера")

        a = self._random_private_a()
        A = pow(g, a, N)
        while A in (0, 1):
            a = self._random_private_a()
            A = pow(g, a, N)

        u = self._pair_hash(A, B)
        k = self._pair_hash(N, g)
        x = self._compute_x(username, password, salt_hex)

        v = self._modpow(g, x, N)
        S = self._modpow(B - k * v, a + u * x, N)
        M1 = int.from_bytes(
            _sha256(_to_byte_array(A) + _to_byte_array(B) + _to_byte_array(S)), "big"
        )

        return SrpProof(_int_to_hex(A), _int_to_hex(M1))


def make_upgrade_verifier_hex(
    modulus_hex, generator_hex, username, password, iterations
):
    N = int(modulus_hex, 16)
    g = int(generator_hex, 16)
    salt = secrets.token_bytes(32)
    x = compute_x_v2(salt.hex(), username, password, iterations)
    v = pow(pow(g, -x, N), -1, N) if x < 0 else pow(g, x, N)
    return (salt + v.to_bytes(128, "big")).hex().upper()
