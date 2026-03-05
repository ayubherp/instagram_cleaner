"""
bot_detector.py - Scores Instagram accounts for bot likelihood
"""

import re


def score_account(user_info, cfg: dict = None) -> dict:
    """
    Returns a score dict. Higher score = more likely a bot.
    Remove if score >= config['min_score'] (default: 3)
    """
    if cfg is None:
        cfg = {}

    flags    = {}
    username = user_info.username
    following = user_info.following_count or 1
    follower  = user_info.follower_count  or 0

    # ── Strong signals ────────────────────────────────────────────────────────
    flags["no_profile_pic"]   = not bool(user_info.profile_pic_url)
    flags["zero_posts"]       = user_info.media_count == 0
    flags["private_no_posts"] = user_info.is_private and user_info.media_count == 0

    # ── Medium signals ────────────────────────────────────────────────────────
    flags["no_bio"]           = not bool(user_info.biography)
    flags["very_new_account"] = (
        user_info.media_count < 3 and
        user_info.follower_count < 10
    )

    # ── Ratio signals ─────────────────────────────────────────────────────────
    flags["follow_bomb"]   = following > 500  and follower < 100
    flags["mass_follower"] = following > 2500

    # following >= N × followers (default 4.0x, adjustable)
    ratio_multiplier = cfg.get('follow_ratio_multiplier', 4.0)
    flags["high_follow_ratio"] = (
        follower > 0 and following >= ratio_multiplier * follower
    ) or (
        follower == 0 and following > 50
    )

    # ── Combined ghost signals (very high confidence) ─────────────────────────

    # No bio + no profile pic + no posts — textbook empty bot account
    flags["full_ghost"] = (
        not bool(user_info.biography) and
        not bool(user_info.profile_pic_url) and
        user_info.media_count == 0
    )

    # Follows 1000+ people but has fewer than 50 followers — pure follow bot
    flags["pure_follow_bot"] = (
        following > 1000 and
        follower < 50
    )

    # ── Username pattern signals ───────────────────────────────────────────────
    flags["numeric_suffix"] = bool(re.search(r'\d{4,}$', username))
    flags["random_chars"]   = bool(re.search(r'[a-z]{2}\d{3}[a-z]{2}', username))

    score = sum(flags.values())

    return {
        "score":    score,
        "flags":    flags,
        "username": username,
    }