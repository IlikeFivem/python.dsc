python.dsc
==========


A modern, easy to use, feature-rich, and async ready API wrapper for Discord written in Python.

Key Features
-------------

- Modern Pythonic API using ``async`` and ``await``.
- Proper rate limit handling.
- Optimised in both speed and memory.

Installing
----------

I have not made any edits to this fork yet. I am gathering some people to come and help out on the project.

**Python 3.8 or higher is required**

To install the library without full voice support, you can just run the following command:

.. code:: sh

    # Linux/macOS
    python3 -m pip install -U python.dsc

    # Windows
    py -3 -m pip install -U python.dsc

Otherwise to get voice support you should run the following command:

.. code:: sh

    # Linux/macOS
    python3 -m pip install -U "python.dsc[voice]"

    # Windows
    py -3 -m pip install -U python.dsc[voice]


To install the development version, do the following:

.. code:: sh

    $ git clone https://github.com/ilikefivem/python.dsc
    $ cd python.dsc
    $ python3 -m pip install -U .[voice]


Optional Packages
~~~~~~~~~~~~~~~~~~

* `PyNaCl <https://pypi.org/project/PyNaCl/>`__ (for voice support)

Please note that on Linux installing voice you must install the following packages via your favourite package manager (e.g. ``apt``, ``dnf``, etc) before running the above commands:

* libffi-dev (or ``libffi-devel`` on some systems)
* python-dev (e.g. ``python3.6-dev`` for Python 3.6)

Quick Example
--------------

.. code:: py

    import discord

    bot = discord.Bot()

    @bot.slah_command(guild_ids=guild_id)
    async def test(ctx):
        await ctx.respond('test')


    bot.run("token")

Bot Example
~~~~~~~~~~~~~

.. code:: py

    import discord
    from discord.ext import commands

    bot = commands.Bot(command_prefix='>')

    @bot.command()
    async def ping(ctx):
        await ctx.send('pong')

    bot.run('token')

You can find more examples in the examples directory.

This is a fork of discord.py that will be maintained!
