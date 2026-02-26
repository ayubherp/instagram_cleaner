config = {
    # Daily limits (stay well under Instagram's thresholds)
    "max_removals_per_day": 700,        # never exceed 700/day
    "max_removals_per_hour": 60,
    
    # Delays (seconds) — randomized to look human
    "delay_between_actions": (8, 20),  # random between 8-20s
    "delay_between_batches": (60, 120),# rest between batches
    "batch_size": 5,                   # actions per batch
    
    # Bot detection thresholds
    "min_bot_score": 3,                # flags needed to remove
    
    # Schedule (run once per day at a random time)
    "run_hour_range": (7, 23),        # only run between 7am-10pm
    
    # Safety
    "whitelist": ["friend1", "brand_collab"],  # never remove these
    "dry_run": False,
}