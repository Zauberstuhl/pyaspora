import base64
import urllib.error
import urllib.parse
import urllib.request
from flask import request
from lxml import etree, html
from sqlalchemy.sql import and_

from pyaspora.contact.models import Contact
from pyaspora.content.models import MimePart
from pyaspora.database import db
from pyaspora.diaspora.models import DiasporaContact, MessageQueue
from pyaspora.diaspora.protocol import DiasporaMessageParser, WebfingerRequest


def addr_for_user(user):
    return "{0}@{1}".format(
        user.id,
        urllib.parse.urlsplit(request.url)['netloc']
    )


def process_incoming_queue(user):
    from pyaspora.diaspora.actions import process_incoming_message

    # FIXME order by time received
    queue_items = db.session.query(MessageQueue).filter(
        and_(
            MessageQueue.format == MessageQueue.INCOMING,
            MessageQueue.local_user == user
        )
    )
    dmp = DiasporaMessageParser(fetch_contact)
    for qi in queue_items:
        ret, c_from = dmp.decode(qi.body.decode('ascii'), user._unlocked_key)
        process_incoming_message(ret, c_from, user)


def fetch_contact(addr):
    dcontact = db.session.query(DiasporaContact).filter(
        DiasporaContact.username == addr).first()
    if dcontact:
        return dcontact.contact

    contact = import_contact(addr)
    db.session.commit()
    return contact


def import_contact(addr):
    """
    Fetch information about a Diaspora user and import it into the Contact
    provided.
    """
    try:
        wf = WebfingerRequest(addr).fetch()
    except urllib.error.URLError:
        return None
    if not wf:
        return None

    NS = {'XRD': 'http://docs.oasis-open.org/ns/xri/xrd-1.0'}

    c = Contact()

    pk = wf.xpath('//XRD:Link[@rel="diaspora-public-key"]/@href',
                  namespaces=NS)[0]
    c.public_key = base64.b64decode(pk).decode("ascii")

    hcard_url = wf.xpath(
        '//XRD:Link[@rel="http://microformats.org/profile/hcard"]/@href',
        namespaces=NS
    )[0]
    hcard = html.parse(urllib.request.urlopen(hcard_url))
    print(etree.tostring(hcard, pretty_print=True))
    c.realname = hcard.xpath('//*[@class="fn"]')[0].text

    photo_url = hcard.xpath('//*[@class="entity_photo"]//img/@src')
    if photo_url:
        resp = urllib.request.urlopen(
            urllib.parse.urljoin(hcard_url, photo_url[0])
        )
        mp = MimePart()
        mp.type = resp.info().get('Content-Type')
        mp.body = resp.read()
        mp.text_preview = '(picture for {})'.format(c.realname)
        c.avatar = mp

    username = wf.xpath('//XRD:Subject/text()', namespaces=NS)[0].split(':')[1]
    guid = wf.xpath(
        ".//XRD:Link[@rel='http://joindiaspora.com/guid']",
        namespaces=NS
    )[0].get("href")
    server = wf.xpath(
        ".//XRD:Link[@rel='http://joindiaspora.com/seed_location']",
        namespaces=NS
    )[0].get("href")
    d = DiasporaContact(
        contact=c,
        guid=guid,
        username=username,
        server=server
    )
    db.session.add(d)
    db.session.add(c)

    return c
