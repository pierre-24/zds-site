{% load i18n %}

{% blocktrans with title=content.title|safe validator_name=validator.username|safe validator_url=validator.get_absolute_url message=message_reject|safe %}

Désolé, « [{{ title }}]({{ url }}) » n'a malheureusement pas passé l’étape de validation.

Mais pas de panique, certaines corrections peuvent surement être faite pour l'améliorer et repasser la validation plus tard.
Voici le message que [{{ validator_name }}]({{ validator_url }}), le validateur, a laissé:

{{ message }}

N'hésite pas a lui envoyer un petit message pour discuter de la décision ou demander plus de détail si tout cela te semble injuste ou manque de clarté !

{% endblocktrans %}