class AuthRouter:
    django_app_labels = {'auth', 'contenttypes', 'admin', 'sessions'}
    naughty_app_label = 'main'
    naughty_models_in_secondary = {}

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.naughty_app_label and model._meta.model_name in self.naughty_models_in_secondary:
            return 'secondary'
        if model._meta.app_label in self.django_app_labels:
            return 'default'
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.naughty_app_label and model._meta.model_name in self.naughty_models_in_secondary:
            return 'secondary'
        if model._meta.app_label in self.django_app_labels:
            return 'default'
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.django_app_labels:
            return db == 'default'
        if app_label == self.naughty_app_label and model_name in self.naughty_models_in_secondary:
            return db == 'secondary'
        return False