"""
Actions/display relating to Contacts. These may be locally-mastered (who
can also do User actions), but they may be Contacts on other nodes using
cached information.
"""

from flask import Blueprint, make_response, request, url_for
from sqlalchemy.sql import desc, or_

from pyaspora.contact import models
from pyaspora.database import db
from pyaspora.tag.views import json_tag
from pyaspora.utils.rendering import abort, add_logged_in_user_to_data, \
    redirect, render_response
from pyaspora.user.session import logged_in_user, require_logged_in_user

blueprint = Blueprint('contacts', __name__, template_folder='templates')


@blueprint.route('/<int:contact_id>/avatar', methods=['GET'])
def avatar(contact_id):
    """
    Display the photo (or other media) that represents a Contact.
    """
    contact = models.Contact.get(contact_id)
    if not contact or not contact.user:
        abort(404, 'No such contact', force_status=True)

    part = contact.avatar
    if not part:
        abort(404, 'Contact has no avatar', force_status=True)

    response = make_response(part.body)
    response.headers['Content-Type'] = part.type
    return response


@blueprint.route('/<int:contact_id>/profile', methods=['GET'])
def profile(contact_id):
    """
    Display the profile (possibly with feed) for the contact.
    """
    from pyaspora.post.models import Post, Share
    from pyaspora.post.views import json_post

    contact = models.Contact.get(contact_id)
    if not contact:
        abort(404, 'No such contact', force_status=True)

    viewing_as = None if request.args.get('public', False) \
        else logged_in_user()

    data = json_contact(contact, viewing_as)
    limit = int(request.args.get('limit', 99))

    # If not local, we don't have a proper feed
    if contact.user:
        # user put it on their public wall
        feed_query = Post.Queries.public_wall_for_contact(contact)
        if viewing_as:
            # Also include things this user has shared with us
            shared_query = Post.Queries.author_shared_with(
                contact, viewing_as)
            feed_query = or_(feed_query, shared_query)
        feed = db.session.query(Post).join(Share).filter(feed_query) \
            .order_by(desc(Post.created_at)).limit(limit)

        data['feed'] = [json_post(p, viewing_as) for p in feed]

    add_logged_in_user_to_data(data, viewing_as)

    return render_response('contacts_profile.tpl', data)


def json_contact(contact, viewing_as=None):
    """
    A suitable representation of the contact that can be turned into JSON
    without too much problem.
    """
    resp = {
        'id': contact.id,
        'link': url_for('contacts.profile',
                        contact_id=contact.id, _external=True),
        'subscriptions': url_for('contacts.subscriptions',
                                 contact_id=contact.id, _external=True),
        'name': contact.realname,
        'bio': '',
        'avatar': None,
        'actions': {
            'add': None,
            'remove': None,
            'post': None,
            'edit': None
        },
        'feed': None,
        'tags': [json_tag(t) for t in contact.interests]
    }
    if contact.avatar:
        resp['avatar'] = url_for('contacts.avatar',
                                 contact_id=contact.id, _external=True)

    if contact.bio:
        resp['bio'] = contact.bio.body.decode('utf-8')

    if viewing_as:
        if viewing_as.id == contact.id:
            resp['actions']['edit'] = url_for('users.info', _external=True)
        if viewing_as.subscribed_to(contact):
            resp['actions']['remove'] = url_for('roster.unsubscribe',
                                                contact_id=contact.id,
                                                _external=True)
        else:
            resp['actions']['post'] = url_for('posts.create',
                                              target='contact',
                                              target_id=contact.id)
            if viewing_as.id != contact.id:
                resp['actions']['add'] = url_for('roster.subscribe',
                                                 contact_id=contact.id,
                                                 _external=True)

    return resp


@blueprint.route('/<int:contact_id>/subscriptions', methods=['GET'])
@require_logged_in_user
def subscriptions(contact_id, _user):
    """
    Display the friend list for the contact (who must be local to this
    server.
    """
    contact = models.Contact.get(contact_id)
    if not contact or not contact.user:
        abort(404, 'No such contact', force_status=True)

    if contact.id == _user.contact.id:
        return redirect(url_for('roster.view', _external=True))

    data = json_contact(contact, _user)
    data['subscriptions'] = [json_contact(c, _user)
                             for c in contact.user.friends()]

    add_logged_in_user_to_data(data, _user)

    return render_response('contacts_friend_list.tpl', data)
