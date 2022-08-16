from distutils.core import setup
import setup_translate


setup(name='enigma2-plugin-systemplugins-extrafancontrol',
		version='0.6',
		author='scriptmelvin',
		author_email='',
		package_dir={'Extensions.infobarweather': 'src'},
		packages=['Extensions.infobarweather'],
		package_data={'Extensions-infobarweather': ['infobarweather']},
		description='InfoBarWeather - Infobar weather plugin',
		cmdclass=setup_translate.cmdclass,
	)
