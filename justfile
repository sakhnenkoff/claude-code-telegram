# claude-code-telegram fork management

# Install from fork (production)
install:
    uv tool install --reinstall git+https://github.com/sakhnenkoff/claude-code-telegram@personal

# Install from local clone (development)
dev:
    uv tool install --reinstall -e .

# Merge upstream changes
upgrade:
    git fetch upstream
    git checkout main && git merge upstream/main && git push origin main
    git checkout personal && git merge main
    @echo ""
    @echo "Resolve conflicts if any, then:"
    @echo "  git push origin personal && just install"

# Run tests
test:
    poetry run pytest tests/ -v

# Restart the bot (launchd will auto-relaunch)
restart:
    killall -9 python3 || true
    @echo "Bot killed. Launchd will auto-relaunch."
