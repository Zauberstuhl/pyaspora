"""
Views relating to tags.
"""
from __future__ import absolute_import

from flask import Blueprint, url_for
from sqlalchemy.sql import desc

from pyaspora.database import db
from pyaspora.tag.models import PostTag, Tag
from pyaspora.user.session import require_logged_in_user
from pyaspora.utils.rendering import abort, add_logged_in_user_to_data, \
    render_response

blueprint = Blueprint('tags', __name__, template_folder='templates')


def json_tag(tag):
    """
    Sensible JSON data structure for a Tag.
    """
    return {
        'id': tag.id,
        'name': tag.name,
        'feed': None,
        'link': url_for('tags.feed', tag_name=tag.name, _external=True)
    }


@blueprint.route('/<string:tag_name>/feed')
@require_logged_in_user
def feed(tag_name, _user):
    """
    Display recent public posts on a particular topic (Tag).
    """
    from pyaspora.post.models import Post, Share
    from pyaspora.post.views import json_posts

    tag = Tag.get_by_name(tag_name, create=False)
    if not tag:
        abort(404, 'No such tag')

    data = json_tag(tag)

    posts = db.session.query(Post). \
        join(PostTag). \
        join(Tag). \
        join(Share). \
        filter(Tag.Queries.public_posts_for_tags([tag.id])). \
        order_by(desc(Post.thread_modified_at)). \
        group_by(Post.id). \
        limit(100)

    data['feed'] = json_posts([(p, None) for p in posts])

    add_logged_in_user_to_data(data, _user)

    return render_response('tags_feed.tpl', data)
