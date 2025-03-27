# complexdispatch

For a long time i've had an issue with singledispatch,
and after enough searching, quite a few other people have it too:

singledispatch cannot handle PEP-585 types: `def _(x: list[ str | int ])`

This seemed like a no brainer, but its been brought up and rejected more than once.
The supposed "solution" is to just do some good old if-routing:

```python
@dispatch.register
def _list_handler(x: list): # i'd love to get more specific, but I cant!
    if all(isinstance(i, str) for i in x):
        # str logic

    if all(isinstance(i, int) for i in x):
        # int logic

    ...

    if all(isinstance(i, (str, int)) for i in x):
        # mixed string and int

    # god forbid we add another, shoot me...
```

Theres nothing inherently wrong with this code,
(except it doesn't type check well)
but this is what I had before. This is the ENTIRE reason I
opted for singledispatch! I refuse to call this a solution,
just to be right back where i was?! Hell no.

So I wrote this.
I changed as little code as I could.
Some I didnt change at all! (but it isnt exposed by functools so it was copied verbatim)

I dont promise this will work for you.
I dont promise its good code.
I dont promise it "follows standards" or behaves how you think it should.

But it solved my problem. I hope it solves yours.
And if not, thats why its open source, you'll figure it out.

KNOWN BUGS:
- caching had to be disabled. (I know, Im not happy about it either. Maybe I'll fix it one day)
