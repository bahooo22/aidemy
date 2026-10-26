# Как поддержать форк

Форк бесплатный, работает офлайн и не требует ключей API. Если коротко: помощь проекту — это прежде всего отзывы, воспроизводимые баг-репорты и правки. Если хочется поддержать автора деньгами, вот способы, которые реально работают из вашей страны.

## DonationAlerts

<https://www.donationalerts.com/r/bahooo>

Там карта, СБП и кошельки — выбор сервиса оставляет себе DonationAlerts, я его не контролирую.

## Крипто-кошельки

| Сеть / Network | Адрес / Address |
|---|---|
| Ethereum (ERC-20 совместимый адрес) | `0x984fE5Bfe7B1573063E20fb3722ba9d4A7a67F04` |
| TON (bounceable, workchain 0) | `UQCHOWrPc1SF_1ZK8pvZP-L1j4mGXmN8JPYrM9GUxJRdOMcf` |

Адрес биткоина появится этой же правкой, как только будет готов.

Перед отправкой сверьте первые и последние шесть символов с этим файлом в `main` (`git log -1 --format=%H -- .github/wallets.md` скажет, когда он менялся в последний раз). Ethereum-адрес прошёл проверку контрольной суммы EIP-55: keccak-256 от строчки в нижнем регистре даёт ровно такое распределение регистра; мерка снята в контейнере стенда на `Crypto.Hash.keccak` (pycryptodome), оба канонических вектора keccak-256 совпали.

Никаких обязательств за донат: доступ к курсам, к коду и к релизам от него не зависит, приватных сборок нет.

---

# Supporting this fork

The fork is free, runs offline and needs no API keys. Short version: the most useful help is a reproducible bug report, a review, a patch. If you would rather support the author with money, here are the channels that work from your country.

## DonationAlerts

<https://www.donationalerts.com/r/bahooo>

Cards, faster payments and wallets there; the service itself is outside my control.

## Crypto wallets

| Network | Address |
|---|---|
| Ethereum (ERC-20 compatible) | `0x984fE5Bfe7B1573063E20fb3722ba9d4A7a67F04` |
| TON (bounceable, workchain 0) | `UQCHOWrPc1SF_1ZK8pvZP-L1j4mGXmN8JPYrM9GUxJRdOMcf` |

The Bitcoin address will land in this same file when it is ready.

Before sending, compare the first and last six characters with this file in `main` (`git log -1 --format=%H -- .github/wallets.md` shows when it last changed). The Ethereum address passes the EIP-55 checksum: keccak-256 over the lowercase string reproduces exactly this letter casing. The check ran inside the stand container with `Crypto.Hash.keccak` (pycryptodome), and both canonical keccak-256 vectors matched.

Donations carry no obligations: access to courses, code and releases does not depend on them, and there is no private build.
