"""
Utilities to convert `banking77` numerical labels to human readable labels and
format into response strings for the agent.

"""

import os

def main():
    print(os.getcwd())

    with open('./template/server/banking77-labels.txt', 'r') as file:
        lines = file.readlines()

    # print(lines[0:3])

    labels = [l.split('\t')[1].strip().replace('_', ' ') for l in lines]

    print(labels[14])

if __name__ == "__main__":
    main()