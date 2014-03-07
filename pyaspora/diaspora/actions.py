from __future__ import absolute_import

from base64 import b64encode, b64decode
from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5 as PKCSSign
from datetime import datetime
from dateutil.tz import tzutc
from flask import url_for
from json import dumps
from lxml import etree
from re import compile as re_compile
try:
    from urllib.error import URLError
    from urllib.parse import urljoin
    from urllib.request import urlopen
except:
    from urllib import urlopen
    from urllib2 import URLError
    from urlparse import urljoin

from pyaspora import db
from pyaspora.content.models import MimePart
from pyaspora.diaspora.models import DiasporaContact, DiasporaPost
from pyaspora.diaspora.protocol import DiasporaMessageBuilder
from pyaspora.diaspora.utils import import_url_as_mimepart
from pyaspora.post.models import Post
from pyaspora.tag.models import Tag
from pyaspora.utils.rendering import ensure_timezone

HANDLERS = {}


def diaspora_message_handler(xpath):
    def _inner(cls):
        HANDLERS[xpath] = cls
        return cls
    return _inner


def process_incoming_message(payload, c_from, u_to):
    xml = payload.lstrip()
    print(xml)
    doc = etree.fromstring(xml)
    for xpath, handler in HANDLERS.items():
        if doc.xpath(xpath):
            return handler.receive(doc, c_from, u_to)
    raise Exception("No handler registered", payload)


class MessageHandlerBase:
    @classmethod
    def _build(cls, u_from, c_to, **kwargs):
        diasp = DiasporaContact.get_for_contact(u_from.contact)
        xml = cls.generate(u_from, c_to, **kwargs)
        m = DiasporaMessageBuilder(xml, diasp.username, u_from._unlocked_key)
        return m

    @classmethod
    def send(cls, u_from, c_to, **kwargs):
        m = cls._build(u_from, c_to, **kwargs)
        url = "{0}receive/users/{1}".format(
            c_to.diasp.server, c_to.diasp.guid)
        print("posting {0} to {1}".format(etree.tostring(m.message), url))
        resp = m.post(url, RSA.importKey(c_to.public_key))
        return resp

    @classmethod
    def send_public(cls, u_from, c_to, **kwargs):
        m = cls._build(u_from, None, **kwargs)
        url = "{0}receive/public".format(c_to.diasp.server)
        print("posting {0} to {1}".format(etree.tostring(m.message), url))
        resp = m.post(url, None)
        return resp

    @classmethod
    def struct_to_xml(cls, node, struct):
        for obj in struct:
            for k, v in obj.items():
                etree.SubElement(node, k).text = v

    @classmethod
    def as_dict(cls, xml):
        node = xml[0][0]
        return {e.tag: e.text for e in node}

    @classmethod
    def format_dt(cls, dt):
        return ensure_timezone(dt).astimezone(tzutc()).strftime(
            '%Y-%m-%d %H:%M:%S %Z'
        )


class SignableMixin:
    @classmethod
    def generate_signature(cls, u_from, node):
        sig_contents = ';'.join([
            e.text for e in node
            if e.text is not None
            and not e.tag.endswith('_signature')
        ])
        sig_hash = SHA256.new(sig_contents.encode("utf-8"))
        cipher = PKCSSign.new(u_from._unlocked_key)
        return b64encode(cipher.sign(sig_hash))

    @classmethod
    def valid_signature(cls, contact, signature, node):
        signature = b64decode(signature)
        sig_contents = ';'.join([
            e.text for e in node
            if e.text is not None
            and not e.tag.endswith('_signature')
        ])
        sig_hash = SHA256.new(sig_contents.encode("utf-8"))
        cipher = PKCSSign.new(RSA.importKey(contact.public_key))
        return cipher.verify(sig_hash, signature)


class TagMixin:
    tag_re = re_compile('#[a-zA-z0-9_]+')

    @classmethod
    def find_tags(cls, text):
        tl = ' '.join(m.group(0)[1:] for m in cls.tag_re.finditer(text))
        return Tag.parse_line(tl, create=True)


@diaspora_message_handler('/XML/post/request')
class Subscribe(MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        """
        Contact c_from has subcribed to u_to
        """
        data = cls.as_dict(xml)
        assert(data['sender_handle'] == c_from.diasp.username)
        c_from.subscribe(u_to.contact)

    @classmethod
    def generate(cls, u_from, c_to):
        req = etree.Element("request")
        cls.struct_to_xml(req, [
            {'sender_handle': u_from.contact.diasp.username},
            {'recipient_handle': c_to.diasp.username}
        ])
        return req


@diaspora_message_handler('/XML/post/profile')
class Profile(MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        data = cls.as_dict(xml)
        assert(data['diaspora_handle'] == c_from.diasp.username)
        c_from.realname = " ".join(
            data.get(k, '') or '' for k in ('first_name', 'last_name')
        )
        c_from.bio = MimePart(
            text_preview=data.get('bio', '(bio)'),
            body=dumps(data).encode('utf-8'),
            type='application/x-pyaspora-diaspora-profile'
        )
        if 'image_url' in data:
            mp = import_url_as_mimepart(urljoin(
                c_from.diasp.server,
                data['image_url']
            ))
            mp.text_preview = '(picture for {})'.format(c_from.realname)
            c_from.avatar = mp
        else:
            c_from.avatar = None

        tags = data.get('tag_string', None) or ''
        tags = ' '.join(tags.split('#'))
        c_from.interests = Tag.parse_line(tags)

        db.session.add(c_from)
        db.session.commit()

    @classmethod
    def generate(cls, u_from, c_to):
        req = etree.Element("profile")
        name_parts = u_from.contact.realname.split(maxsplit=2)
        if len(name_parts) == 1:
            name_parts.append('')
        cls.struct_to_xml(req, [
            {'diaspora_handle': u_from.contact.diasp.username},
            {'first_name': name_parts[0]},
            {'last_name': name_parts[1]},
            {'image_url': url_for(
                'contacts.avatar', contact_id=u_from.contact.id, _external=True
            )},
            {'birthday': None},
            {'gender': None},
            {'location': None},
            {'searchable': 'true'},
            {'nsfw': 'false'},
            {'tag_string': ' '.join(
                '#' + t.name for t in u_from.contact.interests
            )}
        ])
        return req


@diaspora_message_handler('/XML/post/retraction/type[text()="Person"]')
class Unsubscribe(SignableMixin, MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        data = cls.as_dict(xml)
        assert(data['diaspora_handle'] == c_from.diasp.username)
        assert(data['post_guid'] == c_from.diasp.guid)
        c_from.unsubscribe(u_to.contact)

    @classmethod
    def generate(cls, u_from, c_to):
        req = etree.Element("retraction")
        cls.struct_to_xml(req, [
            {'post_guid': u_from.contact.diasp.guid},
            {'type': 'Person'},
            {'diaspora_handle': u_from.contact.diasp.username}
        ])
        return req


@diaspora_message_handler('/XML/post/status_message')
class PostMessage(TagMixin, MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        data = cls.as_dict(xml)
        public = (data['public'] == 'true')
        assert(public or u_to)
        assert(data['diaspora_handle'] == c_from.diasp.username)
        created = datetime.strptime(data['created_at'], '%Y-%m-%d %H:%M:%S %Z')
        p = Post(author=c_from, created_at=created)
        p.add_part(MimePart(
            type='text/x-markdown',
            body=data['raw_message'].encode('utf-8'),
        ), order=0, inline=True)
        p.tags = cls.find_tags(data['raw_message'])
        if public:
            p.share_with([c_from], show_on_wall=True)
        else:
            p.share_with([c_from, u_to.contact])
        p.thread_modified()

        p.diasp = DiasporaPost(
            guid=data['guid'],
            type='public' if public else 'limited'
        )
        db.session.commit()

    @classmethod
    def generate(cls, u_from, c_to, post, text):
        diasp = DiasporaPost.get_for_post(post)
        req = etree.Element("status_message")
        cls.struct_to_xml(req, [
            {'raw_message': text},
            {'guid': diasp.guid},
            {'diaspora_handle': u_from.contact.diasp.username},
            {'public': 'false' if c_to else 'true'},
            {'created_at': cls.format_dt(post.created_at)}
        ])
        return req


@diaspora_message_handler('/XML/post/conversation')
class PrivateMessage(SignableMixin, TagMixin, MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        data = cls.as_dict(xml)
        node = xml.xpath('//message')[0]
        msg = {e.tag: e.text for e in node}
        assert(data['diaspora_handle'] == c_from.diasp.username)
        assert(msg['diaspora_handle'] == c_from.diasp.username)
        assert(cls.valid_signature(c_from, msg['author_signature'], node))
        assert(cls.valid_signature(
            c_from, msg['parent_author_signature'], node
        ))
        assert(data['guid'] == msg['parent_guid'])
        assert(data['guid'] == msg['conversation_guid'])

        created = datetime.strptime(data['created_at'], '%Y-%m-%d %H:%M:%S %Z')
        p = Post(author=c_from, created_at=created)
        part_tags = [t for t in ('subject', 'text') if t in data or t in msg]
        for order, tag in enumerate(part_tags):
            p.add_part(MimePart(
                type='text/x-markdown' if tag == 'text' else 'text/plain',
                body=(data.get(tag, None) or msg[tag]).encode('utf-8'),
            ), order=order, inline=True)
        p.tags = cls.find_tags(data['text'])
        p.share_with([c_from, u_to.contact])
        p.thread_modified()
        db.session.commit()

        p.diasp = DiasporaPost(guid=data['guid'], type='private')
        db.session.commit()

    @classmethod
    def generate(cls, u_from, c_to, post, text):
        req = etree.Element("conversation")
        diasp = DiasporaPost.get_for_post(post)
        cls.struct_to_xml(req, [
            {'guid': diasp.guid},
            {'subject': '(no subject)'},
            {'created_at': cls.format_dt(post.created_at)}
        ])
        msg = etree.SubElement(req, "message")
        cls.struct_to_xml(msg, [
            {'guid': diasp.guid + '-1'},
            {'parent_guid': diasp.guid},
            {'text': text},
            {'created_at': cls.format_dt(post.created_at)},
            {'diaspora_handle': u_from.contact.diasp.username},
            {'conversation_guid': diasp.guid}
        ])
        etree.SubElement(msg, "parent_author_signature").text = \
            cls.generate_signature(u_from, msg)
        etree.SubElement(msg, "author_signature").text = \
            cls.generate_signature(u_from, msg)
        cls.struct_to_xml(req, [
            {'diaspora_handle': u_from.contact.diasp.username},
            {'participant_handles': ';'.join(
                s.contact.diasp.username for s in post.shares
                if s.contact.diasp
            )}
        ])

        return req


@diaspora_message_handler('/XML/post/participation/target_type[text()="Post"]')
class PostParticipation(MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        # Not sure what these do, but they don't seem to be necessary, so do
        # nothing - like Shares?
        pass


@diaspora_message_handler('/XML/post/comment')
class SubPost(SignableMixin, TagMixin, MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        data = cls.as_dict(xml)
        assert(data['diaspora_handle'] == c_from.diasp.username)
        parent = DiasporaPost.get_by_guid(data['parent_guid']).post
        assert(parent)
        if u_to:
            assert(parent.shared_with(c_from))
            assert(parent.shared_with(u_to))
        node = xml[0][0]
        assert(cls.valid_signature(c_from, data['author_signature'], node))
        if 'parent_author_signature' in data:
            assert(
                cls.valid_signature(
                    c_from, data['parent_author_signature'], node
                )
            )

        p = Post(author=c_from)
        p.parent = parent
        p.add_part(MimePart(
            type='text/x-markdown',
            body=data['text'].encode('utf-8'),
        ), order=0, inline=True)
        p.tags = cls.find_tags(data['text'])
        if u_to:
            p.share_with([c_from, u_to.contact])
        else:
            p.share_with([c_from], show_on_wall=True)
        p.thread_modified()

        p.diasp = DiasporaPost(guid=data['guid'])
        db.session.commit()

    @classmethod
    def generate(cls, u_from, c_to, post, text):
        req = etree.Element('comment')
        diasp = DiasporaPost.get_for_post(post)
        p_diasp = DiasporaPost.get_for_post(post.root())

        cls.struct_to_xml(req, [
            {'guid': diasp.guid},
            {'parent_guid': p_diasp.guid},
            {'text': text},
            {'diaspora_handle': u_from.contact.diasp.username}
        ])
        etree.SubElement(req, "author_signature").text = \
            cls.generate_signature(u_from, req)
        if p_diasp.post.author_id == u_from.id:
            etree.SubElement(req, "parent_author_signature").text = \
                cls.generate_signature(u_from, req)
        return req


@diaspora_message_handler('/XML/post/message')
class SubPM(SignableMixin, TagMixin, MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        data = cls.as_dict(xml)
        assert(data['diaspora_handle'] == c_from.diasp.username)
        parent = DiasporaPost.get_by_guid(data['parent_guid']).post
        assert(parent)
        assert(parent.shared_with(c_from))
        assert(parent.shared_with(u_to))
        node = xml[0][0]
        assert(cls.valid_signature(c_from, data['author_signature'], node))
        if 'parent_author_signature' in data:
            assert(cls.valid_signature(
                c_from, data['parent_author_signature'], node
            ))

        created = datetime.strptime(data['created_at'], '%Y-%m-%d %H:%M:%S %Z')
        p = Post(author=c_from, created_at=created)
        p.parent = parent
        p.add_part(MimePart(
            type='text/x-markdown',
            body=data['text'].encode('utf-8'),
        ), order=0, inline=True)
        p.tags = cls.find_tags(data['raw_message'])
        p.share_with([c_from, u_to.contact])
        p.thread_modified()

        p.diasp = DiasporaPost(guid=data['guid'])
        db.session.commit()

    @classmethod
    def generate(cls, u_from, c_to, post, text):
        req = etree.Element('message')
        diasp = DiasporaPost.get_for_post(post)
        p_diasp = DiasporaPost.get_for_post(post.root())

        cls.struct_to_xml(req, [
            {'guid': diasp.guid},
            {'parent_guid': p_diasp.guid},
            {'text': text},
            {'created_at': cls.format_dt(post.created_at)},
            {'diaspora_handle': u_from.contact.diasp.username},
            {'conversation_guid': p_diasp.guid}
        ])
        etree.SubElement(req, "author_signature").text = \
            cls.generate_signature(u_from, req)
        if p_diasp.post.author_id == u_from.id:
            etree.SubElement(req, "parent_author_signature").text = \
                cls.generate_signature(u_from, req)
        return req


@diaspora_message_handler('/XML/post/like')
class Like(MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        # Pyaspora does not support likes
        pass


@diaspora_message_handler('/XML/post/relayable_retraction')
@diaspora_message_handler('/XML/post/signed_retraction')
class Retraction(MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        # Pyaspora does not support deleting posts/PMs
        pass


@diaspora_message_handler('/XML/post/photo')
class Photo(MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        data = cls.as_dict(xml)
        assert(data['diaspora_handle'] == c_from.diasp.username)
        parent = DiasporaPost.get_by_guid(data['guid']).post
        assert(parent)
        assert(parent.shared_with(c_from))
        assert(parent.shared_with(u_to))
        photo_url = urljoin(
            data['remote_photo_path'], data['remote_photo_name']
        )
        resp = urlopen(photo_url)
        mime = resp.info().get('Content-Type')
        parent.add_part(MimePart(
            type=resp.info().get('Content-Type'),
            body=resp.read(),
            text_preview='(picture)'
        ), order=0, inline=bool(mime.startswith('image/')))
        parent.thread_modified()
        db.session.add(parent)
        db.session.commit()


@diaspora_message_handler('/XML/post/reshare')
class Reshare(MessageHandlerBase):
    @classmethod
    def receive(cls, xml, c_from, u_to):
        data = cls.as_dict(xml)
        shared = DiasporaPost.get_by_guid(data['root_guid'])
        assert(shared)
        shared = shared.post
        created = datetime.strptime(data['created_at'], '%Y-%m-%d %H:%M:%S %Z')
        post = Post(author=c_from, created_at=created)
        share_part = MimePart(
            type='application/x-pyaspora-share',
            body=dumps({
                'post': {'id': shared.id},
                'author': {
                    'id': shared.author_id,
                    'name': shared.author.realname,
                }
            }).encode('utf-8'),
            text_preview="shared {0}'s post".format(shared.author.realname)
        )
        post.add_part(share_part, order=0, inline=True)
        order = 0
        for part in shared.parts:
            if part.mime_part.type != 'application/x-pyaspora-share':
                order += 1
                post.add_part(part.mime_part, inline=part.inline, order=order)
        if not post.tags:
            post.tags = shared.tags
        if u_to:
            post.share_with([c_from, u_to.contact])
        else:
            post.share_with([c_from], show_on_wall=True)
        post.thread_modified()

        post.diasp = DiasporaPost(
            guid=data['guid'],
            type='limited' if u_to else 'public'
        )
        db.session.add(post)
        db.session.commit()