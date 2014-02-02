{#
Standard widgets
#}

{%macro small_contact(contact)%}
	{#
	Provide a small representation of a Contact next to content from that Contact.
	#}
	<div class="smallContact">
		{% if contact.avatar %}
			<img src="/contact/avatar/{{ contact.id |e }}" alt="Avatar" class="avatar" />
		{% endif %}
		<strong><a href="/contact/profile/{{ contact.username |e }}">{{ contact.realname |e }}</a></strong>
    </div>
{%endmacro%}

{%macro buttonform(url, text, selected=False, method='post')%}
<form method="{{method}}" action="{{url}}" class='buttonform'>
	<input type='submit' value='{{text}}' class='button{%if selected%} selected{%endif%}' />
</form>
{%endmacro%}

{%macro show_feed(feed)%}
{%for post in feed recursive%}
<div class="feedpost">

	{%for part in post.parts%}
		<div class="postpart">
			{{small_contact(post.author)}}
			{% if part.body.html %}
				{{part.body.html |safe}}
			{% elif part.body.text %}
				<p>
					{{part.body.text |e}}
				</p>
			{% else %}
				<!-- type is {{ part.mime_type |e }} -->
				(cannot display this part: {{part.text_preview|e}})
			{% endif %}
		</div>
	{% endfor %}

		{%if post.actions.comment%}
			{{buttonform(post.actions.comment,'Comment')}}
		{% endif %}
		{%if post.actions.share%}
			{{buttonform(post.actions.share,'Share')}}
		{% endif %}
		{%if post.actions.hide%}
			{{buttonform(post.actions.hide,'Hide')}}
		{% endif %}
		{%if post.actions.make_public%}
			{{buttonform(post.actions.make_public,'Show on public wall')}}
		{% endif %}
		{%if post.actions.unmake_public%}
			{{buttonform(post.actions.unmake_public,'Shown on public wall', True)}}
		{% endif %}

	{% if post.children %}
		{{ loop(post.children) }}
	{% endif %}

</div>
{%endfor%}
{%endmacro%}