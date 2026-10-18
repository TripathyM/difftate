# Roadmap

- **Pluggable diff viewers.** Move every diffity call behind a small adapter (`adapters/diffity.sh`: start, list open threads, reply, edit a comment), so other diff viewers can plug in.
- **Tests and CI.** `shellcheck`, plus a fake adapter and fake agent for end-to-end tests.
- **Known limitation.** A follow-up posted on a thread while the agent is working on that same thread can be missed.
