# coding: utf-8

from datetime import datetime
try:
    import ujson as json_reader
except ImportError:
    try:
        import simplejson as json_reader
    except:
        import json as json_reader

from math import ceil
import shutil
from django.conf import settings
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.db import models
from django.http import Http404
from django.utils.http import urlencode
from django.utils.translation import ugettext_lazy as _
from git import Repo, BadObject
from gitdb.exc import BadName
import os
from uuslug import uuslug
from zds.forum.models import Topic
from zds.gallery.models import Image, Gallery
from zds.tutorialv2.utils import get_content_from_json
from zds.utils import get_current_user
from zds.utils.models import SubCategory, Licence, HelpWriting, Comment
from zds.utils.tutorials import get_blob
from zds.tutorialv2.models import TYPE_CHOICES, STATUS_CHOICES
from zds.tutorialv2.models.models_versioned import NotAPublicVersion


class PublishableContent(models.Model):
    """A tutorial whatever its size or an article.

    A PublishableContent retains metadata about a content in database, such as

    - authors, description, source (if the content comes from another website), subcategory and licence ;
    - Thumbnail and gallery ;
    - Creation, publication and update date ;
    - Public, beta, validation and draft sha, for versioning ;
    - Comment support ;
    - Type, which is either "ARTICLE" or "TUTORIAL"
    """
    class Meta:
        verbose_name = 'Contenu'
        verbose_name_plural = 'Contenus'

    title = models.CharField('Titre', max_length=80)
    slug = models.CharField('Slug', max_length=80)
    description = models.CharField('Description', max_length=200)
    source = models.CharField('Source', max_length=200)
    authors = models.ManyToManyField(User, verbose_name='Auteurs', db_index=True)
    old_pk = models.IntegerField(db_index=True, default=0)
    subcategory = models.ManyToManyField(SubCategory,
                                         verbose_name='Sous-Catégorie',
                                         blank=True, null=True, db_index=True)

    # store the thumbnail for tutorial or article
    image = models.ForeignKey(Image,
                              verbose_name='Image du tutoriel',
                              blank=True, null=True,
                              on_delete=models.SET_NULL)

    # every publishable content has its own gallery to manage images
    gallery = models.ForeignKey(Gallery,
                                verbose_name='Galerie d\'images',
                                blank=True, null=True, db_index=True)

    creation_date = models.DateTimeField('Date de création')
    pubdate = models.DateTimeField('Date de publication',
                                   blank=True, null=True, db_index=True)
    update_date = models.DateTimeField('Date de mise à jour',
                                       blank=True, null=True)

    sha_public = models.CharField('Sha1 de la version publique',
                                  blank=True, null=True, max_length=80, db_index=True)
    sha_beta = models.CharField('Sha1 de la version beta publique',
                                blank=True, null=True, max_length=80, db_index=True)
    sha_validation = models.CharField('Sha1 de la version en validation',
                                      blank=True, null=True, max_length=80, db_index=True)
    sha_draft = models.CharField('Sha1 de la version de rédaction',
                                 blank=True, null=True, max_length=80, db_index=True)
    beta_topic = models.ForeignKey(Topic,
                                   verbose_name='Contenu associé',
                                   default=None,
                                   null=True)
    licence = models.ForeignKey(Licence,
                                verbose_name='Licence',
                                blank=True, null=True, db_index=True)
    # as of ZEP 12 this field is no longer the size but the type of content (article/tutorial)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, db_index=True)
    # zep03 field
    helps = models.ManyToManyField(HelpWriting, verbose_name='Aides', db_index=True)

    relative_images_path = models.CharField(
        'chemin relatif images',
        blank=True,
        null=True,
        max_length=200)

    last_note = models.ForeignKey('ContentReaction', blank=True, null=True,
                                  related_name='last_note',
                                  verbose_name='Derniere note')
    is_locked = models.BooleanField('Est verrouillé', default=False)
    js_support = models.BooleanField('Support du Javascript', default=False)

    public_version = models.ForeignKey(
        'PublishedContent', verbose_name='Version publiée', blank=True, null=True, on_delete=models.SET_NULL)

    def __unicode__(self):
        return self.title

    def textual_type(self):
        if self.is_article():
            return _("L'Article")
        else:
            return _("Le Tutoriel")

    def save(self, *args, **kwargs):
        """
        Rewrite the `save()` function to handle slug uniqueness
        """
        self.slug = uuslug(self.title, instance=self, max_length=80)
        self.update_date = datetime.now()
        super(PublishableContent, self).save(*args, **kwargs)

    def get_absolute_url(self):
        """NOTE: it's better to use the version contained in `VersionedContent`, if possible !

        :return  absolute URL to the draf version the content"""

        return reverse('content:view', kwargs={'pk': self.pk, 'slug': self.slug})

    def get_absolute_url_online(self):
        """NOTE: it's better to use the version contained in `VersionedContent`, if possible !

        :return  absolute URL to the public version the content, if `self.public_version` is defined"""

        if self.public_version:
            return self.public_version.get_absolute_url_online()

        return ''

    def get_absolute_contact_url(self, title=u'Collaboration'):
        """ Get url to send a new PM for collaboration

        :param title: what is going to be in the title of the PM before the name of the content
        :type title: str
        :return: url to the PM creation form
        :rtype: str
        """
        get = '?' + urlencode({'title': u'{} - {}'.format(title, self.title)})

        for author in self.authors.all():
            get += '&' + urlencode({'username': author.username})

        return reverse('mp-new') + get

    def get_repo_path(self, relative=False):
        """Get the path to the tutorial repository

        :param relative: if `True`, the path will be relative, absolute otherwise.
        :return: physical path
        """
        if relative:
            return ''
        else:
            # get the full path (with tutorial/article before it)
            return os.path.join(settings.ZDS_APP['content']['repo_private_path'], self.slug)

    def in_beta(self):
        """A tutorial is not in beta if sha_beta is `None` or empty

        :return: `True` if the tutorial is in beta, `False` otherwise
        """
        return (self.sha_beta is not None) and (self.sha_beta.strip() != '')

    def in_validation(self):
        """A tutorial is not in validation if sha_validation is `None` or empty

        :return: `True` if the tutorial is in validation, `False` otherwise
        """
        return (self.sha_validation is not None) and (self.sha_validation.strip() != '')

    def in_drafting(self):
        """A tutorial is not in draft if sha_draft is `None` or empty

        :return: `True` if the tutorial is in draft, `False` otherwise
        """
        return (self.sha_draft is not None) and (self.sha_draft.strip() != '')

    def in_public(self):
        """A tutorial is not in on line if sha_public is `None` or empty

        :return: `True` if the tutorial is on line, `False` otherwise
        """
        return (self.sha_public is not None) and (self.sha_public.strip() != '')

    def is_beta(self, sha):
        """Is this version of the content the beta version ?

        :param sha: version
        :return: `True` if the tutorial is in beta, `False` otherwise
        """
        return self.in_beta() and sha == self.sha_beta

    def is_validation(self, sha):
        """Is this version of the content the validation version ?

        :param sha: version
        :return: `True` if the tutorial is in validation, `False` otherwise
        """
        return self.in_validation() and sha == self.sha_validation

    def is_public(self, sha):
        """Is this version of the content the published version ?

        :param sha: version
        :return: `True` if the tutorial is in public, `False` otherwise
        """
        return self.in_public() and sha == self.sha_public

    def is_article(self):
        """
        :return: `True` if article, `False` otherwise
        """
        return self.type == 'ARTICLE'

    def is_tutorial(self):
        """
        :return: `True` if tutorial, `False` otherwise
        """
        return self.type == 'TUTORIAL'

    def load_version_or_404(self, sha=None, public=None):
        """Using git, load a specific version of the content. if `sha` is `None`, the draft/public version is used (if
        `public` is `True`).

        :param sha: version
        :param public: if set with the right object, return the public version
        :type public: PublishedContent
        :raise Http404: if sha is not None and related version could not be found
        :return: the versioned content
        """
        try:
            return self.load_version(sha, public)
        except (BadObject, BadName, IOError):
            raise Http404

    def load_version(self, sha=None, public=None):
        """Using git, load a specific version of the content. if `sha` is `None`, the draft/public version is used (if
        `public` is `True`).
        .. attention::
            for practical reason, the returned object is filled with information from DB.

        :param sha: version
        :param public: if set with the right object, return the public version
        :type public: PublishedContent
        :raise BadObject: if sha is not None and related version could not be found
        :raise IOError: if the path to the repository is wrong
        :raise NotAPublicVersion: if the sha does not correspond to a public version
        :return: the versioned content
        """

        # load the good manifest.json
        if sha is None:
            if not public:
                sha = self.sha_draft
            else:
                sha = self.sha_public

        if public and isinstance(public, PublishedContent):  # use the public (altered and not versioned) repository
            path = public.get_prod_path()
            slug = public.content_public_slug

            if not os.path.isdir(path):
                raise IOError(path)

            if sha != public.sha_public:
                raise NotAPublicVersion

            manifest = open(os.path.join(path, 'manifest.json'), 'r')
            json = json_reader.loads(manifest.read())
            versioned = get_content_from_json(json, public.sha_public, slug, public=True)

        else:  # draft version, use the repository (slower, but allows manipulation)
            path = self.get_repo_path()
            slug = self.slug

            if not os.path.isdir(path):
                raise IOError(path)

            repo = Repo(path)
            data = get_blob(repo.commit(sha).tree, 'manifest.json')
            json = json_reader.loads(data)
            versioned = get_content_from_json(json, sha, self.slug)

        self.insert_data_in_versioned(versioned)
        return versioned

    def insert_data_in_versioned(self, versioned):
        """Insert some additional data from database in a VersionedContent

        :param versioned: the VersionedContent to fill
        """

        attrs = [
            'pk', 'authors', 'authors', 'subcategory', 'image', 'creation_date', 'pubdate', 'update_date', 'source',
            'sha_draft', 'sha_beta', 'sha_validation', 'sha_public'
        ]

        fns = [
            'in_beta', 'in_validation', 'in_public', 'is_article', 'is_tutorial', 'get_absolute_contact_url',
            'get_note_count', 'antispam'
        ]

        # load functions and attributs in `versioned`
        for attr in attrs:
            setattr(versioned, attr, getattr(self, attr))
        for fn in fns:
            setattr(versioned, fn, getattr(self, fn)())

        # general information
        versioned.is_beta = self.is_beta(versioned.current_version)
        versioned.is_validation = self.is_validation(versioned.current_version)
        versioned.is_public = self.is_public(versioned.current_version)

    def get_note_count(self):
        """
        :return : umber of notes in the tutorial.
        """
        return ContentReaction.objects.filter(related_content__pk=self.pk).count()

    def get_last_note(self):
        """
        :return: the last answer in the thread, if any.
        """
        return ContentReaction.objects.all()\
            .filter(related_content__pk=self.pk)\
            .order_by('-pubdate')\
            .first()

    def first_note(self):
        """
        :return: the first post of a topic, written by topic's author, if any.
        """
        return ContentReaction.objects\
            .filter(related_content=self)\
            .order_by('pubdate')\
            .first()

    def last_read_note(self):
        """
        :return: the last post the user has read.
        """
        try:
            return ContentRead.objects\
                .select_related()\
                .filter(content=self, user=get_current_user())\
                .latest('note__pubdate').note
        except ContentReaction.DoesNotExist:
            return self.first_post()

    def first_unread_note(self):
        """
        :return: Return the first note the user has unread.
        """
        try:
            last_note = ContentRead.objects\
                .filter(content=self, user=get_current_user())\
                .latest('note__pubdate').note

            next_note = ContentReaction.objects.filter(
                related_content__pk=self.pk,
                pubdate__gt=last_note.pubdate)\
                .select_related("author").first()
            return next_note
        except:  # TODO: `except:` is bad.
            return self.first_note()

    def antispam(self, user=None):
        """Check if the user is allowed to post in an tutorial according to the SPAM_LIMIT_SECONDS value.

        :param user: the user to check antispam. If `None`, current user is used.
        :return: `True` if the user is not able to note (the elapsed time is not enough), `False` otherwise.
        """
        if user is None:
            user = get_current_user()

        if user:
            last_user_notes = ContentReaction.objects\
                .filter(related_content=self)\
                .filter(author=user.pk)\
                .order_by('-position')

            if last_user_notes and last_user_notes[0] == self.last_note:
                last_user_note = last_user_notes[0]
                t = datetime.now() - last_user_note.pubdate
                if t.total_seconds() < settings.ZDS_APP['forum']['spam_limit_seconds']:
                    return True

        return False

    def change_type(self, new_type):
        """Allow someone to change the content type, basically from tutorial to article

        :param new_type: the new type, either `"ARTICLE"` or `"TUTORIAL"`
        """
        if new_type not in TYPE_CHOICES:
            raise ValueError("This type of content does not exist")
        self.type = new_type

    def repo_delete(self):
        """
        Delete the entities and their filesystem counterparts
        """
        shutil.rmtree(self.get_repo_path(), False)
        Validation.objects.filter(content=self).delete()

        if self.gallery is not None:
            self.gallery.delete()
        if self.in_public():
            shutil.rmtree(self.get_prod_path())


class PublishedContent(models.Model):
    """A class that contains information on the published version of a content.

    Used for quick url resolution, quick listing, and to know where the public version of the files are.

    Linked to a ``PublishableContent`` for the rest. Don't forget to add a ``.prefetch_related("content")`` !!
    """

    # TODO: by playing with this class, it may solve most of the SEO problems !!

    class Meta:
        verbose_name = 'Contenu publié'
        verbose_name_plural = 'Contenus publiés'

    content = models.ForeignKey(PublishableContent, verbose_name='Contenu')

    content_type = models.CharField(max_length=10, choices=TYPE_CHOICES, db_index=True, verbose_name='Type de contenu')
    content_public_slug = models.CharField('Slug du contenu publié', max_length=80)
    content_pk = models.IntegerField('Pk du contenu publié', db_index=True)

    publication_date = models.DateTimeField('Date de publication', db_index=True, blank=True, null=True)
    sha_public = models.CharField('Sha1 de la version publiée', blank=True, null=True, max_length=80, db_index=True)

    must_redirect = models.BooleanField(
        'Redirection vers  une version plus récente', blank=True, db_index=True, default=False)

    def __unicode__(self):
        return _('Version publique de "{}"').format(self.content.title)

    def get_prod_path(self, relative=False):
        if not relative:
            return os.path.join(settings.ZDS_APP['content']['repo_public_path'], self.content_public_slug)
        else:
            return ''

    def get_absolute_url_online(self):
        """
        :return: the URL of the published content
        """
        reversed_ = ''

        if self.is_article():
            reversed_ = 'article'
        elif self.is_tutorial():
            reversed_ = 'tutorial'

        return reverse(reversed_ + ':view', kwargs={'pk': self.content_pk, 'slug': self.content_public_slug})

    def is_article(self):
        return self.content_type == "ARTICLE"

    def is_tutorial(self):
        return self.content_type == "TUTORIAL"

    def get_extra_contents_directory(self):
        """
        :return: path to all the "extra contents"
        """
        return os.path.join(self.get_prod_path(), settings.ZDS_APP['content']['extra_contents_dirname'])

    def have_type(self, type_):
        """check if a given extra content exists

        :return: `True` if the file exists, `False` otherwhise
        """

        allowed_types = ['pdf', 'md', 'html', 'epub', 'zip']

        if type_ in allowed_types:
            return os.path.isfile(
                os.path.join(self.get_extra_contents_directory(), self.content_public_slug + '.' + type_))

        return False

    def have_md(self):
        """Check if the markdown version of the content is available

        :return: `True` if available, `False` otherwise
        """
        return self.have_type('md')

    def have_html(self):
        """Check if the html version of the content is available

        :return: `True` if available, `False` otherwise
        """
        return self.have_type('html')

    def have_pdf(self):
        """Check if the pdf version of the content is available

        :return: `True` if available, `False` otherwise
        """
        return self.have_type('pdf')

    def have_epub(self):
        """Check if the standard epub version of the content is available

        :return: `True` if available, `False` otherwise
        """
        return self.have_type('epub')

    def have_zip(self):
        """Check if the standard epub version of the content is available

        :return: `True` if available, `False` otherwise
        """
        return self.have_type('zip')

    def get_absolute_url_to_extra_content(self, type_):
        """
        :return: URL to a given extra content (note that no check for existence is done)
        """

        allowed_types = ['pdf', 'md', 'html', 'epub', 'zip']

        if type_ in allowed_types:
            reversed_ = ''

            if self.is_article():
                reversed_ = 'article'
            elif self.is_tutorial():
                reversed_ = 'tutorial'

            return reverse(
                reversed_ + ':download-' + type_, kwargs={'pk': self.content_pk, 'slug': self.content_public_slug})

        return ''

    def get_absolute_url_md(self):
        """
        :return: URL to the full markdown version of the published content
        """

        return self.get_absolute_url_to_extra_content('md')

    def get_absolute_url_html(self):
        """
        :return: URL to the HTML version of the published content
        """

        return self.get_absolute_url_to_extra_content('html')

    def get_absolute_url_pdf(self):
        """
        :return: URL to the PDF version of the published content
        """

        return self.get_absolute_url_to_extra_content('pdf')

    def get_absolute_url_epub(self):
        """
        :return: URL to the epub version of the published content
        """

        return self.get_absolute_url_to_extra_content('epub')

    def get_absolute_url_zip(self):
        """
        :return: URL to the zip archive of the published content
        """

        return self.get_absolute_url_to_extra_content('zip')


class ContentReaction(Comment):
    """
    A comment written by any user about a PublishableContent he just read.
    """
    class Meta:
        verbose_name = 'note sur un contenu'
        verbose_name_plural = 'notes sur un contenu'

    related_content = models.ForeignKey(PublishableContent, verbose_name='Contenu',
                                        related_name="related_content_note", db_index=True)

    def __unicode__(self):
        return u'<Tutorial pour "{0}", #{1}>'.format(self.related_content, self.pk)

    def get_absolute_url(self):
        """
        :return: the url of the comment
        """
        page = int(ceil(float(self.position) / settings.ZDS_APP["content"]["notes_per_page"]))
        return '{0}?page={1}#p{2}'.format(self.related_content.get_absolute_url_online(), page, self.pk)


class ContentRead(models.Model):
    """
    Small model which keeps track of the user viewing tutorials.

    It remembers the PublishableContent he looked and what was the last Note at this time.
    """
    class Meta:
        verbose_name = 'Contenu lu'
        verbose_name_plural = 'Contenu lus'

    content = models.ForeignKey(PublishableContent, db_index=True)
    note = models.ForeignKey(ContentReaction, db_index=True, null=True)
    user = models.ForeignKey(User, related_name='content_notes_read', db_index=True)

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        """
        Save this model but check that if we have not a related note it is because the user is content author.
        """
        if self.user not in self.content.authors.all() and self.note is None:
            raise ValueError("Must be related to a note or be an author")

        return super(ContentRead, self).save(force_insert, force_update, using, update_fields)

    def __unicode__(self):
        return u'<Contenu "{}" lu par {}, #{}>'.format(self.content, self.user, self.note.pk)


class Validation(models.Model):
    """
    Content validation.
    """
    class Meta:
        verbose_name = 'Validation'
        verbose_name_plural = 'Validations'

    content = models.ForeignKey(PublishableContent, null=True, blank=True,
                                verbose_name='Contenu proposé', db_index=True)
    version = models.CharField('Sha1 de la version',
                               blank=True, null=True, max_length=80, db_index=True)
    date_proposition = models.DateTimeField('Date de proposition', db_index=True, null=True, blank=True)
    comment_authors = models.TextField('Commentaire de l\'auteur', null=True, blank=True)
    validator = models.ForeignKey(User,
                                  verbose_name='Validateur',
                                  related_name='author_content_validations',
                                  blank=True, null=True, db_index=True)
    date_reserve = models.DateTimeField('Date de réservation',
                                        blank=True, null=True)
    date_validation = models.DateTimeField('Date de validation',
                                           blank=True, null=True)
    comment_validator = models.TextField('Commentaire du validateur',
                                         blank=True, null=True)
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='PENDING')

    def __unicode__(self):
        return _(u'Validation de « {} »').format(self.content.title)

    def is_pending(self):
        """Check if the validation is pending

        :return: `True` if status is pending, `False` otherwise
        """
        return self.status == 'PENDING'

    def is_pending_valid(self):
        """Check if the validation is pending (but there is a validator)

        :return: `True` if status is pending, `False` otherwise
        """
        return self.status == 'PENDING_V'

    def is_accept(self):
        """Check if the content is accepted

        :return: `True` if status is accepted, `False` otherwise
        """
        return self.status == 'ACCEPT'

    def is_reject(self):
        """Check if the content is rejected

        :return: `True` if status is rejected, `False` otherwise
        """
        return self.status == 'REJECT'

    def is_cancel(self):
        """Check if the content is canceled

        :return: `True` if status is canceled, `False` otherwise
        """
        return self.status == 'CANCEL'