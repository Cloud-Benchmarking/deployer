import logging
import glob
import logging
import logging.handlers


LOG_FILENAME = 'logging_rotatingfile_example.out'

if __name__ == '__main__':
    logger = logging.getLogger('scope.name')
    logger.setLevel('INFO')
    file_log_handler = logging.FileHandler('logfile.log')
    logger.addHandler(file_log_handler)

    stderr_log_handler = logging.StreamHandler()
    logger.addHandler(stderr_log_handler)

    # nice output format
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_log_handler.setFormatter(formatter)
    stderr_log_handler.setFormatter(formatter)

    logger.info('Info message')
    logger.error('Error message')
