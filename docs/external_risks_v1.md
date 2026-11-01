# External risks

> **Status:** Written 2026-11-01. Report only. **Nothing has been sent.** The Azure host name is left out of this public repo on purpose.
> **Scope:** the NSE terms question, the Azure endpoint, and what the AI forward test depends on.

## 1. Draft query on NSE data terms

For you to review and send, to NSE's data-products team or a lawyer. Replace the brackets. This is a draft and not legal advice.

> **Subject: Personal research use of NSE public files and pages**
>
> I am an individual in India, researching my own trading decisions. I am not reselling or redistributing data. I would like a written answer on whether the following use is permitted, and what licence, if any, it needs.
>
> 1. One automated download each trading evening of published archive files: F&O bhavcopy, participant open interest, MTO delivery and index closes.
> 2. One automated capture each evening of option-chain bid and ask for about 31 symbols, from the website's data endpoint.
> 3. A live option-chain request when I ask for one in a personal app, a few times a day.
> 4. Storing these files on my own computer for research, including history back to 2010.
> 5. Publishing code on a public GitHub repository, without any data, and publishing summary research results derived from the data. [Confirm this matches what you do.]
>
> Please also tell me whether any of this falls under your terms of use or requires a data licence, and whom to contact if it does.
>
> Regards, [name and contact]

**For the lawyer, add:** whether the website's terms bind personal research use; whether derived statistics and backtest results in a public repository are redistribution; and any exposure from past downloads.

**Your own open decision of 2026-10-30:** the nightly job runs unchanged until you report back. No answer is recorded.

## 2. Azure endpoint: what to confirm

The host name and config file are in the chat report, not here. Please confirm:

1. Who owns the subscription: you, or an organisation?
2. If an organisation, may it be used for personal trading research, and for market data sent in prompts?
3. Who pays, and can access be withdrawn?
4. Does the deployment update its model version by itself? This is UNVERIFIED and affects the forward test.

Whose it is cannot be told from the code.

## 3. What the AI forward test depends on

| Dependency | Used for | When it fails | Effect on the test |
|---|---|---|---|
| Azure model access | Each question | No answer | No row is written; that day becomes missed |
| Same model and prompt | The hash | The name or prompt changes: nothing counts, and a warning is logged. **A version change behind the same name goes undetected** | A new test, or a hidden break |
| NSE live option chain | Question, then entry | No chain: no answer, or the trade is void | Missed, or a recorded void trade |
| NSE nightly files | Final settlement at expiry | A gap: the trade stays open until the price exists | A delay; a permanent gap leaves it unsettled, and that rule isn't in the spec |
| NSE terms | All of the above | If use is refused, data stops | The test ends; no rule for this is in the spec |
| You, each session | Asking the question | A missed day | Recorded, never filled; the verdict moves later |
| Web app running | The hook | No question is possible | Same as a missed day |
| Disk: `reports/ai_test/` | Registry and chains | Lost or corrupted disk | Restore from a backup; rows since it are lost, and those days cannot be refilled |
| Backup in `C:\\Users\\ASUS\\.tradingagents\\backups\\ai_test` | Recovery | **Same disk as the source**, run by hand | A disk failure loses both |
| Windows scheduled tasks | Nightly data | Machine off: no run, later catch-up not guaranteed | Settlement delayed |
| Settlement script | Results | Locked until you approve; reading store prices isn't built | No results until then |
