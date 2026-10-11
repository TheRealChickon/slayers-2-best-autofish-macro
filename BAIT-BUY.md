Run this while standing at Baitmonger Nori with the shop dialogue open and the farmer paused:

```
autofish bait buy --budget 200k
autofish bait buy --quantity 1000
autofish bait status
autofish bait resume
autofish bait resume --budget 169k --then-full --overnight
autofish full --restart --overnight
```

The budget is gold; quantity/amount is additional Fish Heads. A 200k budget buys 22,222 Fish Heads for 199,998 gold. Transactions use batches of up to 99, with the final batch limited to the exact remaining quantity. The command verifies the seller, Fish Head selection, quoted amount, price and gold debit. It never clicks Robux items or travels to the seller.

Dialogue-body clicks advance text faster. Each Deal is sent once, followed by verification of its exact debit. An interrupted transaction remains pending; resume verifies its debit before buying the remainder. An uncertain result stays blocked.

On resume, an explicit new budget or quantity replaces the REMAINING allowance after any pending transaction is reconciled. `resume --budget 169k` buys at most 18,777 more Fish Heads for 168,993 gold. Omitting the amount preserves the original remaining amount. `--then-full` starts Full farmer only after verified purchase completion; `--overnight` also enables overnight autofocus and idle activation.

The keyboard CLI shows these options under Settings > Buy bait. Enter edits Purchase amount; Amount type switches between gold and bait quantity; After purchase optionally selects Full farmer. Buy bait now launches the same CLI buyer. Run > Reset + start Full farmer stops the current controller and rejoins at the saved spawn, retaining run counters and logs. Reopen an already running CLI display after installing an update to load the new menu.

Escape, F8, F9, F12, Pause/Stop, focus loss or a changed window releases input. Existing run counters and saved pause settings are retained. The farmer cannot start while a buyer holds the controller lease.
