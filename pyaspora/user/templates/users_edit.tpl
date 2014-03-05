{#
Sign-up form for creating a new account on the local server.
#}
{% extends "layout.tpl" %}

{% block content %}
<h2>Edit profile</h2>

<form method="post" action="{{url_for('.edit')}}" enctype="multipart/form-data">

<h3>Name</h3>
<p>
    <input name="name" value="{{name}}" />
</p>

<h3>Bio</h3>
<p>
    Tell everyone about yourself:<br />
    <textarea name="bio">{{bio}}</textarea>
</p>

<h3>Profile photo</h3>

<p>
    Choose a photo of yourself to display on your profile:
    <input type="file" name="avatar" />
</p>

<h3>Interests</h3>

<p>
    Enter your interests here, separated by spaces. Interests should consist
    of lower-case letters, numbers and underscores, such as
    <tt>kittens</tt>,
    <tt>sliced_bread</tt> and
    <tt>channel_9</tt>:<br />
    <input type="text" name="tags" value="{% for tag in tags %}{{tag.name}}{% if not loop.last %} {% endif %}{% endfor %}" />
</p>

<h3>Account settings</h3>

<p>Notify me about new content and messages
    <select name="notification_frequency_hours">
        <option value=""{% if not notification_frequency_hours %} selected="selected"{%endif%}>never</option>
        <option value="1"{% if notification_frequency_hours and 24 > notification_frequency_hours >= 1 %} selected="selected"{%endif%}>no more than once an hour</option>
        <option value="24"{% if notification_frequency_hours and 168 > notification_frequency_hours >= 24 %} selected="selected"{%endif%}>no more than once a day</option>
        <option value="168"{% if notification_frequency_hours and notification_frequency_hours >= 168 %} selected="selected"{%endif%}>no more than once a week</option>
    </select>
</p>

<p>
    <input type="submit" value="Save" class="button" />
</p>

</form>
{% endblock %}
