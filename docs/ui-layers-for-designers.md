# Layers: building a screen element out of pieces

A button used to be one picture in one box. Now it can be a stack: the button
art, a Munchkin on top of it, an icon, a background behind it — each piece
placed, coloured and skinned on its own, all of it done in the editor. Those
extra pieces are called **layers**.

This is the walkthrough. No code, no JSON.

## Adding a layer

1. Open the editor (`py editor/main.py`) and go to the screen you want.
2. In the **outliner** on the left, click the widget you want to build on — the
   Pause button, the love counter, whatever it is.
3. Click **Add layer**. The new layer appears as a child of that widget, like a
   file inside a folder. Give it art from the picker, or leave the art empty and
   give it a colour or some text instead — a layer is whichever of those you
   fill in first: art wins over text, text wins over a plain colour block.
4. Drag it in the viewport to place it, or type exact numbers in the inspector.

A layer is **pinned to its widget**, not to the screen. Wherever the widget ends
up, the layer travels with it — so if the game moves the love counter, its
background moves too. You never have to re-place it.

Add as many as you like. Remove one with **Remove layer**. Everything here is
undoable, the same as every other edit.

## Giving it a hover colour

A layer can look different depending on what the mouse is doing. There are four
looks: **Idle** (nothing happening), **Hover** (mouse over it), **Pressed**
(mouse held down on it) and **Disabled** (greyed out, not usable right now).

At the top of the layer inspector there is a **state selector**. Whichever state
it shows is the one you are editing. Switch it to **Hover**, change the colour,
switch back to **Idle** — the idle colour is untouched. Same for position: you
can nudge a layer a pixel or two on Pressed so it feels like it depresses.

Anything you don't set for a state falls back to what Idle looks like, so you
only ever author the differences.

**One catch.** Hover, Pressed and Disabled only mean something on a real button.
On a plain label, panel or backdrop the game has nothing tracking the mouse, so
those three states can never happen. The editor greys them out on those widgets
rather than letting you author a look nothing will ever show.

## Under vs Over — read this one

Every layer sits either **Under** or **Over**, and the difference is bigger than
it sounds.

**Over** does what you expect: the layer draws on top of its widget.

**Under** draws the layer behind *the whole screen* — not just behind the widget
it belongs to. Everything else on that screen sits in front of it.

So: a background panel behind the love counter, with nothing else meant to be
near it? **Under** is right. Something that needs to sit between two panels that
are already stacked on top of each other? **Under** will bury it behind both —
use **Over** and place it carefully instead.

This is a real limit of how the screen is drawn, not a bug, and it will not
change without a redesign. The editor repeats this warning on the band control
so you meet it while placing, not later in the game.

## Making a layer clickable

Tick **Clickable** and the layer becomes its own click target — the Munchkin on
the Pause button can do something different from the Pause button underneath it.

Then set **Target**, which is what the click actually does. Three options:

- **Point it at another button on the same screen.** Type or pick that button's
  name and your layer fires whatever that button does. Point the Munchkin at End
  Turn and clicking the Munchkin ends the turn — while clicking the rest of the
  Pause button still pauses. The two can never drift apart, because your layer is
  reusing the real button, not a copy of it.
- **Use one of the three special destinations**: `close_window` closes the window
  you're in, `back` goes back a screen, `noop` does nothing on purpose.
- **`noop` is not the same as leaving Clickable off.** An unticked layer is
  invisible to the mouse — the click goes straight through to whatever is behind
  it. A `noop` layer catches the click and stops it. Use `noop` when a decoration
  is sitting on top of a button and you *don't* want people accidentally pressing
  that button through it.

### The warning, and why the editor lets you save a broken one

The Target box is a free text field with suggestions, not a fixed menu. You can
type the name of a button that doesn't exist yet — deliberately, so you can lay
out a screen before someone has built the thing it points at.

When you do, an **amber warning appears under the box**. It means: this will
save, and it will look fine, but the click won't go anywhere. In the game, that
layer will *eat* the click — it won't do its job, and it won't let the click fall
through to what's behind it either. It will simply feel dead.

That warning is the only thing standing between a typo and a dead button. Nothing
downstream catches it. So if you see amber, either create the button you named or
fix the spelling before you hand the screen over.

## Where to look when something's wrong

- Layer is invisible → check the state selector; you may have authored it on
  Hover while looking at Idle. Also check the **Visible** tick.
- Layer draws behind things it shouldn't → it's on **Under**. See above.
- Click does nothing → check for the amber Target warning, and check
  **Clickable** is actually ticked.
- Layer doesn't follow its widget → it can't not. If it looks detached, its
  offset is just large; the numbers are distances *from* the widget, not
  positions on the screen.
