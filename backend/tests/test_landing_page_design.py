"""The upgraded landing-page chrome (G3): a professional, self-contained look.

Non-brittle checks — the exact palette can evolve, but the page must keep the
capture form intact, ship the polish hallmarks (focus state, responsive dark
mode), and never emit CSS the HTML-scaffold guard strips from authored bodies.
"""

from __future__ import annotations

from app.services import sites as sites_svc


def test_page_keeps_capture_form_and_bare_h1():
    html = sites_svc.render_page_html(
        "Acme",
        "# Grow autonomously\n\n- Fast\n- Real",
        form_action="https://api.example.com/p/sites/abc/subscribe",
        cta_headline="Join the waitlist",
        cta_button="Get early access",
    )
    # Structure the form + tests depend on is preserved by the restyle.
    assert '<form class="abos-capture"' in html
    assert 'name="email"' in html and 'name="website"' in html  # honeypot
    assert ">Join the waitlist</h3>" in html and ">Get early access</button>" in html
    assert "<h1>Acme</h1>" in html  # h1 stays bare (styled by element selector)


def test_page_ships_the_brand_look():
    html = sites_svc.render_page_html("t", "b")
    # The GalaxiaOS brand: midnight base + indigo accent (matches the app), and a focus ring.
    assert "#0d1320" in html  # midnight background
    assert "#6366f1" in html  # logo indigo accent
    assert ":focus" in html
    # Must not use CSS the authored-HTML guard strips (else chrome would render
    # inconsistently vs. bodies) — see test_render_page_html_degrades_authored_html.
    # (A radial glow is fine; only linear-gradient/.hero{ are stripped.)
    assert "linear-gradient" not in html
    assert ".hero{" not in html
