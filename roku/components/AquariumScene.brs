' All motion runs on Animation nodes (render thread); BrightScript only picks a
' new random path each time a fish or bubble finishes its trip.

sub init()
    m.top.backgroundColor = "0x0A2A44FF"

    m.layers = {
        far: m.top.findNode("farLayer"),
        mid: m.top.findNode("midLayer"),
        near: m.top.findNode("nearLayer")
    }

    m.top.findNode("bgDrift").control = "start"
    for each id in ["rayShimmer0", "rayShimmer1", "rayShimmer2", "raySway"]
        m.top.findNode(id).control = "start"
    end for

    m.fish = []
    m.clock = CreateObject("roTimespan")
    m.shark = invalid
    m.holdFish = false
    species = ParseJson(ReadAsciiFile("pkg:/images/fish.json"))
    if species = invalid then species = []
    ' Every species appears once; a coin flip gives some a second fish, up to
    ' maxDoubles in total. With 10 solo species and 2 schools of 5-7 that caps
    ' the tank at 30 fish.
    maxDoubles = 6
    doubles = 0
    ' Shuffle so the cap doesn't always favour species listed first.
    for i = species.count() - 1 to 1 step -1
        j = Rnd(i + 1) - 1
        tmp = species[i] : species[i] = species[j] : species[j] = tmp
    end for
    for each s in species
        if s.kind = "school"
            for i = 1 to 2
                addFish(s, 4 + Rnd(3))
            end for
        else if s.kind = "shark"
            addShark(s)
        else
            addFish(s, 1)
            if doubles < maxDoubles and Rnd(2) = 1
                addFish(s, 1)
                doubles = doubles + 1
            end if
        end if
    end for
    ' Stagger first appearances so the tank doesn't fill all at once.
    for each f in m.fish
        if not f.isShark then swim(f, rand(0, 14))
    end for

    ' Bubble sources come from decor (see addDecor) and critters' hiding spots
    ' (see addCritters).
    m.emitters = []
    addDecor()
    addCritters()

    ' The scene is fully built: report launch complete (certification 3.2).
    ' Roku docs don't say whether screensavers need this, and forum reports say
    ' it may log "not reachable" from RunScreenSaver(); it's harmless either way.
    m.top.signalBeacon("AppLaunchComplete")

#if DEBUG_OVERLAY
    addDebugOverlay()
#end if

    m.bubbles = []
    for each e in m.emitters
        for i = 1 to e.count
            addBubble(e, rand(0, 9))
        end for
    end for
end sub

#if DEBUG_OVERLAY
' Diagnostic only (package.py --debug): a red frame on the edges of the
' 1920x1080 design canvas and the resolution the device actually renders at.
' If the frame isn't fully visible, the screen is being zoomed or cropped.
sub addDebugOverlay()
    for each r in [[0, 0, 1920, 6], [0, 1074, 1920, 6], [0, 0, 6, 1080], [1914, 0, 6, 1080]]
        edge = m.top.createChild("Rectangle")
        edge.translation = [r[0], r[1]]
        edge.width = r[2]
        edge.height = r[3]
        edge.color = "0xFF2020FF"
    end for
    for each c in [[960, 540], [6, 6], [1914, 1074]]
        dot = m.top.createChild("Rectangle")
        dot.translation = [c[0] - 10, c[1] - 10]
        dot.width = 20
        dot.height = 20
        dot.color = "0xFFFF00FF"
    end for

    ' FormatJson prints whatever the device returns, so a missing or
    ' differently typed field can't crash the diagnostic.
    di = CreateObject("roDeviceInfo")
    info = "design " + FormatJson(m.top.currentDesignResolution)
    info = info + "   ui " + FormatJson(di.GetUIResolution())
    info = info + "   display " + FormatJson(di.GetDisplaySize()) + " " + di.GetDisplayMode()
    info = info + "   model " + di.GetModel() + "   OS " + FormatJson(di.GetOSVersion())
    print "AquariumTV debug: "; info

    infoBox = m.top.createChild("Rectangle")
    infoBox.translation = [100, 50]
    infoBox.width = 1720
    infoBox.height = 120
    infoBox.color = "0x000000B0"
    label = infoBox.createChild("Label")
    label.translation = [20, 0]
    label.width = 1680
    label.height = 120
    label.wrap = true
    label.horizAlign = "center"
    label.vertAlign = "center"
    label.color = "0xFFFFFFFF"
    label.text = info
end sub
#end if

function rand(lo as float, hi as float) as float
    return lo + (hi - lo) * Rnd(0)
end function

' A bubble source. While inactive, bubbles that finish rising wait in
' `waiting` instead of relaunching (see setEmitterActive).
function newEmitter(layer as object, x as float, y as float, spread as float, count as integer) as object
    return { layer: layer, x: x, y: y, spread: spread, count: count, active: true, waiting: [] }
end function

function hex2(v as integer) as string
    return Right("0" + StrI(v, 16), 2)
end function

' ---------------------------------------------------------------- decor

sub addDecor()
    layer = m.top.findNode("foreground")
    items = ParseJson(ReadAsciiFile("pkg:/images/decor.json"))
    if items = invalid then return
    for each d in items
        if d.bubbles > 0
            ' Bubbles live in the foreground with the decor, so they drift with
            ' it, and sit just behind it so they rise out from among the blades.
            m.emitters.push(newEmitter(layer.createChild("Group"), d.x + d.w / 2, d.y + d.h * 0.6, d.w * 0.15, d.bubbles))
        end if
        p = layer.createChild("Poster")
        p.id = "decor_" + d.id
        p.uri = "pkg:/images/fg_" + d.id + ".png"
        p.translation = [d.x, d.y]
        p.width = d.w
        p.height = d.h
        if d.sway > 0
            ' Sway from the base, like it's anchored in the sand.
            p.scaleRotateCenter = [d.w / 2, d.h]
            a = p.createChild("Animation")
            a.duration = d.swayPeriod
            a.repeat = true
            a.easeFunction = "inOutQuad"
            i = a.createChild("FloatFieldInterpolator")
            i.fieldToInterp = p.id + ".rotation"
            i.key = [0.0, 0.5, 1.0]
            i.keyValue = [-d.sway, d.sway, -d.sway]
            a.control = "start"
        end if
    end for
end sub

' ---------------------------------------------------------------- critters

' A critter hides in the cave (its home), creeps out onto the sand, stands in
' the open for a while, then retreats. Inside the cave it's blacked out and
' transparent, so it seems to emerge from the darkness. Coordinates are in
' background-image pixels (critterLayer drifts with the background).
sub addCritters()
    layer = m.top.findNode("critterLayer")
    items = ParseJson(ReadAsciiFile("pkg:/images/critters.json"))
    if items = invalid then return
    m.critters = []
    for each c in items
        idx = m.critters.count()
        emitter = invalid
        if c.bubbles > 0
            ' Bubbles drift up out of the hiding spot, but only while the critter
            ' is tucked away inside (see onCritterEmerge / onCritterState).
            g = layer.createChild("Group")
            g.id = "critterBubbles" + idx.toStr()
            emitter = newEmitter(g, c.bubbleFrom[0], c.bubbleFrom[1], 20, c.bubbles)
            ' Bubbles start dim inside the dark hiding spot and brighten as they
            ' rise out of it (see launchBubble).
            emitter.darkUntil = c.bubbleDarkUntil
            emitter.litBy = c.bubbleLitBy
            fade = g.createChild("Animation")
            fade.duration = 1.5
            fade.easeFunction = "linear"
            fi = fade.createChild("FloatFieldInterpolator")
            fi.fieldToInterp = g.id + ".opacity"
            fi.key = [0.0, 1.0]
            fi.keyValue = [1.0, 0.0]
            emitter.fade = fade
            m.emitters.push(emitter)
        end if
        p = layer.createChild("Poster")
        p.id = "critter" + idx.toStr()
        p.uri = "pkg:/images/critter_" + c.id + ".png"
        p.width = c.w
        p.height = c.h
        p.scaleRotateCenter = [c.w / 2, c.h]
        p.opacity = 0

        anim = p.createChild("Animation")
        anim.id = "critterAnim" + idx.toStr()
        anim.easeFunction = "linear"
        cr = { poster: p, anim: anim, spec: c, emitter: emitter }
        if emitter <> invalid
            ' Fires when a trip's delay is over, i.e. as the critter starts out.
            cr.timer = layer.createChild("Timer")
            cr.timer.id = "critterTimer" + idx.toStr()
            cr.timer.repeat = false
            cr.timer.observeField("fire", "onCritterEmerge")
        end if
        for each f in ["translation", "scale", "blendColor", "opacity", "rotation"]
            if f = "translation" or f = "scale"
                interp = anim.createChild("Vector2DFieldInterpolator")
            else if f = "blendColor"
                interp = anim.createChild("ColorFieldInterpolator")
            else
                interp = anim.createChild("FloatFieldInterpolator")
            end if
            interp.fieldToInterp = p.id + "." + f
            cr[f] = interp
        end for
        anim.observeField("state", "onCritterState")
        m.critters.push(cr)
        critterTrip(cr, rand(10, 30))
    end for
end sub

sub onCritterState(event as object)
    if event.getData() <> "stopped" then return
    cr = m.critters[Val(Mid(event.getNode(), 12))]
    ' Back in hiding: bubbles resume.
    if cr.emitter <> invalid then setEmitterActive(cr.emitter, true)
    critterTrip(cr, rand(20, 70))
end sub

sub onCritterEmerge(event as object)
    cr = m.critters[Val(Mid(event.getNode(), 13))]
    setEmitterActive(cr.emitter, false)
end sub

sub setEmitterActive(e as object, active as boolean)
    e.active = active
    if active
        e.fade.control = "stop"
        e.layer.opacity = 1
        for each b in e.waiting
            launchBubble(b, rand(0, 4))
        end for
        e.waiting = []
    else
        ' Bubbles still rising fade away; none relaunch until reactivated.
        e.fade.control = "start"
    end if
end sub

sub critterTrip(cr as object, delay as float)
    c = cr.spec
    home = c.home
    mouth = c.mouth
    ' Keep the whole body on open sand, not just the feet's centre point.
    minX = c.sandX[0] + c.w / 2
    maxX = c.sandX[1] - c.w / 2
    outPt = [rand(minX, maxX), rand(c.sandY[0], c.sandY[1])]
    ' A slow, deliberate creep out, a long look around, then back.
    duration = rand(80, 95)

    black = &h000000FF
    shadow = &h2A3444FF
    lit = &hCBE4FFFF
    hs = c.homeScale
    ms = hs + (1 - hs) * 0.35
    ' key:    hidden  mouth   out     stand   mouth   hidden  rest
    keys = [0.0, 0.14, 0.30, 0.70, 0.86, 0.98, 1.0]
    points = [home, mouth, outPt, outPt, mouth, home, home]
    scales = [hs, ms, 1.0, 1.0, ms, hs, hs]
    colors = [black, shadow, lit, lit, shadow, black, black]
    alphas = [0.0, 0.85, 1.0, 1.0, 0.85, 0.0, 0.0]

    ' Poster translation is its top-left; points are where its feet go.
    translations = []
    scaleValues = []
    for i = 0 to keys.count() - 1
        translations.push([points[i][0] - c.w / 2, points[i][1] - c.h])
        scaleValues.push([scales[i], scales[i]])
    end for
    cr.translation.key = keys
    cr.translation.keyValue = translations
    cr.scale.key = keys
    cr.scale.keyValue = scaleValues
    cr.blendColor.key = keys
    cr.blendColor.keyValue = colors
    cr.opacity.key = keys
    cr.opacity.keyValue = alphas

    ' Scuttle (a quick side-to-side rock) only while walking.
    rk = []
    rv = []
    walking = [[0.0, 0.30], [0.70, 0.98]]
    stepT = 0.6 / duration
    rk.push(0.0) : rv.push(0.0)
    for each seg in walking
        ' Hold still (0) right up to the start of each walk, not drift into it.
        if seg[0] > rk[rk.count() - 1] then rk.push(seg[0]) : rv.push(0.0)
        t = seg[0] + stepT
        sign = 1
        while t < seg[1]
            rk.push(t) : rv.push(0.012 * sign)
            sign = -sign
            t = t + stepT
        end while
        rk.push(seg[1]) : rv.push(0.0)
    end for
    rk.push(1.0) : rv.push(0.0)
    cr.rotation.key = rk
    cr.rotation.keyValue = rv

    cr.anim.duration = duration
    cr.anim.delay = delay
    cr.anim.control = "start"
    if cr.emitter <> invalid
        if delay < 0.05 then delay = 0.05
        cr.timer.duration = delay
        cr.timer.control = "start"
    end if
end sub

' ---------------------------------------------------------------- fish

sub addFish(species as object, count as integer)
    idx = m.fish.count()
    group = CreateObject("roSGNode", "Group")
    group.id = "fish" + idx.toStr()
    group.translation = [-2000, 0]
    ' Attach first so the interpolators below can resolve their target ids.
    m.layers.mid.appendChild(group)

    posters = []
    for i = 0 to count - 1
        p = group.createChild("Poster")
        ' Schools get a loose, random formation around the leader.
        if i > 0 then p.translation = [rand(-1.6, 1.6) * species.w, rand(-1.2, 1.2) * species.h]
        posters.push(p)
        addWiggle(p, group.id + "p" + i.toStr())
    end for

    anim = group.createChild("Animation")
    anim.id = "swim" + idx.toStr()
    anim.easeFunction = "linear"
    interp = anim.createChild("Vector2DFieldInterpolator")
    interp.fieldToInterp = group.id + ".translation"
    anim.observeField("state", "onSwimState")

    f = { species: species, group: group, posters: posters, anim: anim, interp: interp }
    f.isShark = false
    f.held = false
    f.visibleAt = 0
    m.fish.push(f)
end sub

' A gentle, endless tail-beat: squash the sprite horizontally around its centre.
sub addWiggle(poster as object, id as string)
    poster.id = id
    a = poster.createChild("Animation")
    a.duration = rand(0.5, 0.9)
    a.repeat = true
    a.easeFunction = "inOutQuad"
    a.delay = rand(0, 0.5)
    i = a.createChild("Vector2DFieldInterpolator")
    i.fieldToInterp = id + ".scale"
    i.key = [0.0, 0.5, 1.0]
    i.keyValue = [[1.0, 1.0], [0.95, 1.02], [1.0, 1.0]]
    a.control = "start"
end sub

sub onSwimState(event as object)
    if event.getData() <> "stopped" then return
    f = m.fish[Val(Mid(event.getNode(), 5))]
    if f.isShark
        sharkGone()
    else if f.held
        ' Parked by onSharkTimer; it'll be relaunched by sharkGone.
    else if m.holdFish
        holdFish(f)
    else
        swim(f, rand(1, 10))
    end if
end sub

' ---------------------------------------------------------------- shark

' A rare visitor. sharkLead seconds before it sets off, new fish stop entering:
' ones already on screen finish their trip and then wait, so the tank has
' thinned out by the time it arrives (about 4 of ~19 fish left, by simulation).
' Once it's gone they start coming back after 1 second.
sub addShark(species as object)
    addFish(species, 1)
    m.shark = m.fish[m.fish.count() - 1]
    m.shark.isShark = true
    ' Slow, heavy tail beats instead of the small fish flutter.
    wiggle = m.shark.posters[0].getChild(0)
    wiggle.duration = 1.6
    wiggle.getChild(0).keyValue = [[1.0, 1.0], [0.97, 1.01], [1.0, 1.0]]

    m.sharkLead = 30
    m.sharkTimer = m.top.createChild("Timer")
    m.sharkTimer.repeat = false
    m.sharkTimer.observeField("fire", "onSharkTimer")
    scheduleShark(rand(90, 150))
end sub

' The timer fires twice per visit: once to start holding fish back, then
' sharkLead seconds later to send the shark in.
sub scheduleShark(secondsUntilShark as float)
    m.sharkPhase = "hold"
    m.sharkTimer.duration = secondsUntilShark - m.sharkLead
    m.sharkTimer.control = "start"
end sub

sub onSharkTimer()
    if m.sharkPhase = "hold"
        m.holdFish = true
        now = m.clock.TotalMilliseconds()
        for each f in m.fish
            ' Park anything that hasn't reached the screen yet, even if its
            ' trip has technically started in the off-screen margin.
            if not f.isShark and not f.held and f.visibleAt > now then holdFish(f)
        end for
        m.sharkPhase = "go"
        m.sharkTimer.duration = m.sharkLead
        m.sharkTimer.control = "start"
    else
        swim(m.shark, 0.5)
    end if
end sub

sub holdFish(f as object)
    f.held = true
    f.anim.control = "stop"
    f.group.translation = [-3000, 0]
end sub

sub sharkGone()
    m.holdFish = false
    for each f in m.fish
        if f.held
            f.held = false
            ' All restart 1 s after the shark leaves; each still takes a moment to
            ' swim in from its off-screen start, so they don't arrive in one burst.
            swim(f, 1)
        end if
    end for
    scheduleShark(rand(100, 160))
end sub

sub swim(f as object, delay as float)
    s = f.species
    depth = rand(0.45, 1.0)
    ' The shark always passes close to the glass.
    if f.isShark then depth = rand(0.85, 1.0)
    w = s.w * depth
    h = s.h * depth

    ' Move between depth layers so near fish pass in front of far ones.
    if depth < 0.65 then
        layer = m.layers.far
    else if depth < 0.85 then
        layer = m.layers.mid
    else
        layer = m.layers.near
    end if
    parent = f.group.getParent()
    if parent = invalid or not parent.isSameNode(layer)
        if parent <> invalid then parent.removeChild(f.group)
        layer.appendChild(f.group)
    end if

    goingRight = Rnd(2) = 1
    if goingRight then side = "r" else side = "l"
    ' Smaller sprite for distant fish (matches FAR_SCALE in tools/process.py).
    if depth < 0.7 then side = side + "_far"
    ' Distant fish fade toward the water colour.
    tint = Int(140 + 115 * (depth - 0.45) / 0.55)
    blend = "0x" + hex2(tint) + hex2(Int(tint * 0.5 + 127)) + "FFFF"
    for each p in f.posters
        p.uri = "pkg:/images/fish_" + s.id + "_" + side + ".png"
        p.width = w
        p.height = h
        p.scaleRotateCenter = [w / 2, h / 2]
        p.blendColor = blend
    end for
    ' Schools trail behind the leader whichever way they swim.
    for i = 1 to f.posters.count() - 1
        base = f.posters[i].translation
        dx = Abs(base[0])
        if goingRight then dx = -dx
        f.posters[i].translation = [dx, base[1]]
    end for

    margin = w * 2.5
    baseY = rand(120, 960 - h)
    amp = rand(10, 60) * depth
    waves = rand(1, 3)
    if f.isShark
        ' Long and solo, so it needs little margin; cruise the open water above
        ' the reef in a slow, shallow undulation.
        margin = w + 40
        baseY = rand(120, 440)
        amp = rand(8, 20)
        waves = rand(0.5, 1.2)
    end if
    if goingRight
        x0 = -margin : x1 = 1920 + margin
    else
        x0 = 1920 + margin : x1 = -margin
    end if
    phase = rand(0, 6.28)
    steps = 8
    keys = []
    values = []
    for i = 0 to steps
        t = i / steps
        keys.push(t)
        y = baseY + amp * Sin(phase + t * waves * 6.283)
        values.push([x0 + (x1 - x0) * t, y])
    end for
    f.interp.key = keys
    f.interp.keyValue = values

    speed = rand(45, 110) * depth
    if s.kind = "school" then speed = speed * 1.4
    if f.isShark then speed = rand(75, 90)
    f.anim.duration = Abs(x1 - x0) / speed
    ' When the leading edge first reaches the screen (onSharkTimer uses this).
    f.visibleAt = m.clock.TotalMilliseconds() + (delay + (margin - w) / speed) * 1000
    f.anim.delay = delay
    f.group.translation = values[0]
    f.anim.control = "start"
end sub

' ---------------------------------------------------------------- bubbles

sub addBubble(emitter as object, delay as float)
    idx = m.bubbles.count()
    p = emitter.layer.createChild("Poster")
    p.id = "bubble" + idx.toStr()
    p.uri = "pkg:/images/bubble.png"
    p.translation = [0, 1200]
    anim = p.createChild("Animation")
    anim.id = "bubbleAnim" + idx.toStr()
    anim.easeFunction = "inQuad"
    interp = anim.createChild("Vector2DFieldInterpolator")
    interp.fieldToInterp = p.id + ".translation"
    anim.observeField("state", "onBubbleState")
    b = { poster: p, anim: anim, interp: interp, emitter: emitter }
    if emitter.darkUntil <> invalid
        b.color = anim.createChild("ColorFieldInterpolator")
        b.color.fieldToInterp = p.id + ".blendColor"
        b.fade = anim.createChild("FloatFieldInterpolator")
        b.fade.fieldToInterp = p.id + ".opacity"
    end if
    m.bubbles.push(b)
    launchBubble(b, delay)
end sub

sub onBubbleState(event as object)
    if event.getData() <> "stopped" then return
    idx = Val(Mid(event.getNode(), 11))
    launchBubble(m.bubbles[idx], rand(0, 3))
end sub

sub launchBubble(b as object, delay as float)
    if not b.emitter.active
        b.emitter.waiting.push(b)
        return
    end if
    size = rand(8, 26)
    b.poster.width = size
    b.poster.height = size
    b.poster.opacity = rand(0.5, 0.9)
    e = b.emitter
    x = e.x + rand(-e.spread, e.spread)
    ' Rise from the source to just past the top of the screen.
    rise = e.y + 80
    keys = []
    values = []
    for i = 0 to 6
        t = i / 6
        keys.push(t)
        values.push([x + Sin(t * 9 + rand(0, 1)) * 14, e.y - t * rise])
    end for
    b.interp.key = keys
    b.interp.keyValue = values
    if b.color <> invalid
        ' Fractions of the rise where the bubble leaves the dark and is fully lit.
        fDark = (e.y - e.darkUntil) / rise
        fLit = (e.y - e.litBy) / rise
        op = b.poster.opacity
        b.color.key = [0.0, fDark, fLit, 1.0]
        b.color.keyValue = [&h1A2230FF, &h3A4658FF, &hFFFFFFFF, &hFFFFFFFF]
        b.fade.key = [0.0, fDark, fLit, 1.0]
        b.fade.keyValue = [op * 0.15, op * 0.35, op, op]
    end if
    ' Bigger bubbles rise faster; same speed whatever the starting height.
    b.anim.duration = rand(7, 10) * (26 / (size + 26)) * 2 * rise / 1080
    b.anim.delay = delay
    b.anim.control = "start"
end sub
