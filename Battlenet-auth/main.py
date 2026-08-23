import asyncio

from battlenet_auth.client import BattleNetClient
from battlenet_auth.exceptions import BattleNetError

region = "eu"
locale = "ru"


async def main():
    email = input("Почта: ")
    password = input("Пароль: ")

    client = BattleNetClient(region=region, locale=locale)
    try:
        result = await client.login(email, password, on_code=input)
        cookies = result.cookies

        if result.authorized:
            print("[Auth] OK")
            print(f"[Auth] srp={result.used_srp} v{result.srp_version}")
            print(f"[Auth] ST={result.ticket}")
            print(
                f'[Auth] account={result.account_id} {result.account.get("battleTag", "")}'
            )
            return

        raise BattleNetError("авторизация не подтверждена")
    except BattleNetError as ex:
        print(f"[Auth] Fail: {ex}")
    finally:
        await client.close()


asyncio.run(main())
