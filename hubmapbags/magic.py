import os
import pandas as pd
from pathlib import Path
from shutil import rmtree, copy
from shutil import move
from os import remove
import logging
import glob
import os.path
from os import listdir
from os.path import isfile, join, exists
import warnings

from . import collection_anatomy, collection_compound, \
              biosample_substance, biosample_gene, assay_type, \
              biosample_disease, anatomy, \
              file_describes_collection, project_in_project, \
              file_describes_biosample, file_describes_subject, \
              biosample_from_subject, subject, \
              subject_in_collection, ncbi_taxonomy, \
              id_namespace, biosample_in_collection, \
              file_in_collection, primary_dcc_contact, \
              biosample, projects, \
              collection, anatomy, \
              file as files, collection_defined_by_project, \
              collection_disease, collection_gene, \
              collection_phenotype, collection_protein, \
              collection_substance, collection_taxonomy, \
              collection_in_collection, subject_disease, \
              subject_phenotype, subject_race, \
              subject_role_taxonomy, subject_substance, \
              file_format, apis, \
              uuids, utilities

def __extract_dataset_info_from_db( id, token=None, instance='test', debug=None ):
	'''
	Helper function that uses the HuBMAP APIs to get dataset info.
	'''

	j = apis.get_dataset_info( id, token=token, instance=instance )
	if j is None:
		warnings.warn('Unable to extract data from database.')
		return None

	hmid = j.get('hubmap_id')
	hmuuid = j.get('uuid')
	status = j.get('status')
	data_types = j.get('data_types')[0]
	group_name = j.get('group_name')
	group_uuid = j.get('group_uuid')
	first_sample_id=j.get('direct_ancestors')[0].get('hubmap_id')
	first_sample_uuid=j.get('direct_ancestors')[0].get('uuid')

	j = apis.get_provenance_info( id, instance=instance, token=token )
	organ_type=j.get('organ_type')[0]
	organ_hmid=j.get('organ_hubmap_id')[0]
	organ_uuid=j.get('organ_uuid')[0]
	donor_hmid=j.get('donor_hubmap_id')[0]
	donor_uuid=j.get('donor_uuid')[0]

	full_path = os.path.join('/hive/hubmap/data/public',hmuuid)
	if not os.path.isdir(full_path):
		full_path=os.path.join('/hive/hubmap/data/protected',group_name,hmuuid)

	headers = ['ds.group_name', 'ds.uuid', \
		'ds.hubmap_id', 'dataset_uuid', \
		'ds.status', 'ds.data_types', \
		'first_sample_id', 'first_sample_uuid', \
		'organ_type', 'organ_id', \
		'donor_id', 'donor_uuid', \
		'full_path']

	df = pd.DataFrame(columns=headers)
	df = df.append({'ds.group_name':group_name, \
		'ds.uuid':group_uuid, \
		'ds.hubmap_id':hmid, \
		'dataset_uuid':hmuuid, \
		'ds.data_types':data_types, \
		'ds.status':status, \
		'ds.data_types':data_types, \
		'first_sample_id':first_sample_id, \
		'first_sample_uuid':first_sample_uuid, \
		'organ_type':organ_type, \
		'organ_id':organ_hmid, \
		'donor_id':donor_hmid, \
		'donor_uuid':donor_uuid, \
		'full_path':full_path}, ignore_index=True)

	return df

def __get_number_of_files( output_directory ):
	'''
	Helper function that returns the number of files in a directory.
	'''
	try:
		return len([name for name in os.listdir( output_directory ) if os.path.isfile( os.path.join( output_directory, name ))])
	except:
		return 0

def do_it( input, dbgap_study_id=None, \
	 	compute_uuids=False, \
		overwrite=False, \
		copy_output_to=None, \
		token=None, \
		instance='test', \
		debug=True ):
	'''
	Magic function that builds computes checksums, generates UUIDs and builds a bdbag from a HuBMAP ID.
	'''

	if os.path.isfile( input ):
		utilities.pprint('Extracting datasets from ' + input)
		metadata_file = input
		datasets = pd.read_csv( metadata_file, sep='\t' )
	else:	
		utilities.pprint('Processing dataset with HuBMAP ID ' + input)
		datasets = __extract_dataset_info_from_db( input, token=token, instance=instance )
		if datasets is None:
			warnings.warn('No datasets found. Exiting.')
			return False

	print( 'Number of datasets found is ' + str(datasets.shape[0]) )
	for dataset in datasets.iterrows():
		dataset = dataset[1]
		status = dataset['ds.status'].lower()
		data_type = dataset['ds.data_types'].replace('[','').replace(']','').replace('\'','').lower()
		data_provider = dataset['ds.group_name']
		hubmap_id = dataset['ds.hubmap_id']
		hubmap_uuid = dataset['dataset_uuid']
		biosample_id = dataset['first_sample_id']
		data_directory = dataset['full_path']
		print('Preparing bag for dataset ' + data_directory )
		computing = data_directory.replace('/','_').replace(' ','_') + '.computing'
		done = '.' + data_directory.replace('/','_').replace(' ','_') + '.done'
		broken = '.' + data_directory.replace('/','_').replace(' ','_') + '.broken'
		organ_shortcode = dataset['organ_type']
		organ_id = dataset['organ_id']
		donor_id = dataset['donor_id']

		if overwrite:
			print('Erasing old checkpoint. Re-computing checksums.')
			if Path(done).exists():
				Path(done).unlink()

		if Path(done).exists():
			print('Checkpoint found. Avoiding computation. To re-compute erase file ' + done)
		elif Path(computing).exists():
			print('Computing checkpoint found. Avoiding computation since another process is building this bag.')
		else:
			with open(computing, 'w') as file:
				pass

			print('Creating checkpoint ' + computing)

			if status == 'new':
				print('Dataset is not published. Aborting computation.')
				return

			print('Checking if output directory exists.')
			output_directory = data_type + '-' + status + '-' + dataset['dataset_uuid']

			print('Creating output directory ' + output_directory + '.' )
			if Path(output_directory).exists() and Path(output_directory).is_dir():
					print('Output directory found. Removing old copy.')
					rmtree(output_directory)
					os.mkdir(output_directory)
			else:
					print('Output directory does not exist. Creating directory.')
					os.mkdir(output_directory)

			print('Making file.tsv')
			temp_file = data_directory.replace('/','_').replace(' ','_') + '.pkl'

			if overwrite:
				print('Removing precomputed checksums')
				if Path(temp_file).exists():
					Path(temp_file).unlink()
			answer = files.create_manifest( project_id=data_provider, \
				assay_type=data_type, \
				directory=data_directory, \
				output_directory=output_directory, \
				dbgap_study_id=dbgap_study_id, \
				token=token, \
				dataset_hmid=hubmap_id, \
				dataset_uuid=hubmap_uuid )

			print('Making biosample.tsv')
			biosample.create_manifest( biosample_id, data_provider, organ_shortcode, output_directory )

			print('Making biosample_in_collection.tsv')
			biosample_in_collection.create_manifest( biosample_id, hubmap_id, output_directory )

			print('Making project.tsv')
			projects.create_manifest( data_provider, output_directory )

			print('Making project_in_project.tsv')
			project_in_project.create_manifest( data_provider, output_directory )

			print('Making biosample_from_subject.tsv')
			biosample_from_subject.create_manifest( biosample_id, donor_id, output_directory )

			print('Making ncbi_taxonomy.tsv')
			ncbi_taxonomy.create_manifest( output_directory )

			print('Making collection.tsv')
			collection.create_manifest( hubmap_id, output_directory )

			print('Making collection_defined_by_project.tsv')
			collection_defined_by_project.create_manifest( hubmap_id, data_provider, output_directory )

			print('Making file_describes_collection.tsv')
			file_describes_collection.create_manifest( hubmap_id, data_directory, output_directory )

			print('Making dcc.tsv')
			primary_dcc_contact.create_manifest( output_directory )        

			print('Making id_namespace.tsv')
			id_namespace.create_manifest( output_directory )

			print('Making subject.tsv')
			subject.create_manifest( data_provider, donor_id, output_directory )

			print('Making subject_in_collection.tsv')
			subject_in_collection.create_manifest( donor_id, hubmap_id, output_directory )

			print('Making file_in_collection.tsv')
			answer = file_in_collection.create_manifest( hubmap_id, data_directory, output_directory )

			print('Creating empty files')
			file_describes_subject.create_manifest( output_directory )
			file_describes_biosample.create_manifest( output_directory )
			anatomy.create_manifest( output_directory )
			assay_type.create_manifest( output_directory )
			biosample_disease.create_manifest( output_directory )
			biosample_gene.create_manifest( output_directory )
			biosample_substance.create_manifest( output_directory )
			collection_anatomy.create_manifest( output_directory )
			collection_compound.create_manifest( output_directory )
			collection_disease.create_manifest( output_directory )
			collection_gene.create_manifest( output_directory )
			collection_in_collection.create_manifest( output_directory )
			collection_phenotype.create_manifest( output_directory )
			collection_protein.create_manifest( output_directory )
			collection_substance.create_manifest( output_directory )
			collection_taxonomy.create_manifest( output_directory )
			file_format.create_manifest( output_directory )
			ncbi_taxonomy.create_manifest( output_directory )
			subject_disease.create_manifest( output_directory )
			subject_phenotype.create_manifest( output_directory )
			subject_race.create_manifest( output_directory )
			subject_role_taxonomy.create_manifest( output_directory )
			subject_substance.create_manifest( output_directory )
			file_format.create_manifest( output_directory )

			print('Removing checkpoint ' + computing )
			Path(computing).unlink()

			print('Creating final checkpoint ' + done )
			if __get_number_of_files( output_directory ) == 36:
				with open(done, 'w') as file:
					pass
			else:
				warnings.warn('Wrong number of output files. Labeling dataset as broken.')
				with open(broken, 'w') as file:
					pass

			if copy_output_to is not None:
				print('Checking if output directory destination exists')
				if Path(copy_output_to).exists() and Path(copy_output_to).is_dir():
					print('Copying file ' + temp_file + ' to ' + copy_output_to + '.')
					try:
						copy( temp_file, copy_output_to )
					except:
						print('Unable to copy file to destination. Check permissions.')

					print('Moving directory ' + output_directory + ' to ' + copy_output_to + '.')
					try:
						if Path(os.path.join(copy_output_to, output_directory)).exists():
							rmtree(os.path.join(copy_output_to, output_directory))
						move( output_directory, copy_output_to )
					except Exception as e:
						print('Unable to move folder to destination. Check permissions.')
						print(e)
				else:
					warnings.warn('Output directory ' + copy_output_to + ' does not exist. Not copying results to destination.')

			if compute_uuids:
				print('Generating UUIDs via the uuid-api')
				if uuids.should_i_generate_uuids( hubmap_id=id, \
					filename=temp_file, \
					instance=instance, \
					token=token, \
					debug=debug):
					print('UUIDs not found in uuid-api database. Generating UUIDs.')
					uuids.generate( temp_file, debug=debug )
				else:
					print('UUIDs found in uuid-api database. Populating local file')
					uuids.populate_local_file_with_remote_uuids( hubmap_id, \
						instance=instance, \
						token=token, \
						debug=debug )
			if debug:
				df=pd.read_pickle( temp_file )
				df.to_csv(temp_file.replace('pkl','tsv'), sep="\t")

	return True
