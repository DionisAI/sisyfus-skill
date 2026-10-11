"""Phone dispatch for Sisyfus research: start headless research jobs and read status remotely.

The dispatch server is opt-in and private by default. It only runs research in
operator-allowlisted project directories; the phone never supplies a path,
command or argv. See `sisyfus dispatch --help`.
"""
