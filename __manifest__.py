{
    'name': "Odoo Database Manager",

    'summary': "Database Manager and backup automation",

    'description': """
Long description of module's purpose
    """,

    'author': "Ridwan Aden",
    'website': "https://www.yourcompany.com",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Extra Tools',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base','mail'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/database_backup_views.xml',
        'views/database_storage_views.xml',
        'views/menu.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
    ],
}

