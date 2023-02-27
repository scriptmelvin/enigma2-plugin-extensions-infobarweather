from distutils.core import setup
import setup_translate


pkg='Extensions.InfoBarWeather'
setup(name='enigma2-plugin-extensions-infobarweather',
		version='0.18',
		author='scriptmelvin',
		author_email='',
		package_dir={pkg: 'plugin'},
		packages=[pkg],
		package_data={pkg: ['*.png', '*/*.png', '*/*/*.png', 'locale/*/LC_MESSAGES/*.mo']},
		description='Show current weather in infobar',
		license='GPLv2',
		cmdclass=setup_translate.cmdclass
	)
