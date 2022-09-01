import io

import matplotlib.pyplot as plt

########

scale = 1.25  # default 1.25
dpi = 900

labels_font_size = None  # if None label size will set automatically by my algo

labels_font_size_map = {
    # number_of_layers: labels_font_size
    0: 7,
    1: 7,
    2: 6,
    3: 5,
    4: 4,
    5: 3,
    6: 2,
    7: 2,
    8: 2,
    9: 2,
    10: 2,
}
labels_font_size_in_other_cases = 2


########


def get_subject_dict(list_of_subject_paths):
    subject_dict = {}

    for subject_path in list_of_subject_paths:
        subject_path = subject_path.strip()
        subject_list = subject_path.split('/')

        gag = subject_dict
        for element in subject_list:
            if element in gag:
                gag[element]['count'] += 1
            else:
                gag[element] = {
                    'count': 1,
                    'sub_dict': {}
                }
            gag = gag[element]['sub_dict']

    return subject_dict


def add_other_cells_to_subject_dict(subject_dict, layer):
    gag_sum = 0
    for key in subject_dict:
        gag_sum += subject_dict[key]['count']

    for key in subject_dict:
        subject_dict[key]['coefficient'] = subject_dict[key]['count'] / gag_sum

        count = subject_dict[key]['count']
        sub_dict = subject_dict[key]['sub_dict']

        sum = 0
        for key2 in sub_dict:
            sum += sub_dict[key2]['count']

        if count != sum and layer < number_of_layers - 1:
            sub_dict[''] = {
                'count': count - sum,
                'sub_dict': {}
            }

        add_other_cells_to_subject_dict(sub_dict, layer + 1)


def get_color(color_index, layer):
    color_index = color_index % 10
    if color_index < 5:
        color_map = plt.colormaps['tab20c']
    else:
        color_index -= 5
        color_map = plt.colormaps['tab20b']

    if number_of_layers > 4:
        layer = round(layer / number_of_layers * 3)

    my_color_map = {
        0: {0: 0, 1: 1, 2: 2, 3: 3},
        1: {0: 4, 1: 5, 2: 6, 3: 7},
        2: {0: 8, 1: 9, 2: 10, 3: 11},
        3: {0: 12, 1: 13, 2: 14, 3: 15},
        4: {0: 16, 1: 17, 2: 18, 3: 19},
    }

    color_number = my_color_map[color_index][layer]
    color = color_map(color_number)
    return color


def form_layers_dict(subjects_dict, layer, color_index=None, zero_layer=False):
    if color_index is None:
        color_index = 0

    for key in subjects_dict:
        count = subjects_dict[key]['count']
        layers_dict[layer]['numbers'].append(count)

        coefficient = subjects_dict[key]['coefficient']
        percent = round(coefficient * 100)

        if coefficient != 1.0 or key:
            label = f'{percent}% | {count}'
            if key:
                label = f'{key} | ' + label
        else:
            label = ''
        layers_dict[layer]['labels'].append(label)

        layers_dict[layer]['colors'].append(get_color(color_index, layer))

        form_layers_dict(subjects_dict[key]['sub_dict'], layer + 1, color_index)

        if zero_layer:
            color_index += 1


def get_pie(list_of_subject_paths: list, day, day1=None, format='jpg'):
    new_list_of_subject_paths = []

    without_subject = 0
    for subject_path in list_of_subject_paths:
        if subject_path is None:
            without_subject += 1
        else:
            new_list_of_subject_paths.append(subject_path)

    list_of_subject_paths = sorted(new_list_of_subject_paths)

    for i in range(without_subject):
        list_of_subject_paths.append('without subject')

    global number_of_layers
    number_of_layers = 0
    for subject_path in list_of_subject_paths:
        subject_path = subject_path.strip()
        split = subject_path.split('/')
        if number_of_layers < len(split):
            number_of_layers = len(split)

    # print(f'number_of_layers: {number_of_layers}')
    # print('-' * 64)

    subject_dict = get_subject_dict(list_of_subject_paths)

    # print('subject_dict:')
    # print(json.dumps(subject_dict, indent=4))
    # print('-' * 64)

    add_other_cells_to_subject_dict(subject_dict, 0)

    # print('subject_dict:')
    # print(json.dumps(subject_dict, indent=4))
    # print('-' * 64)

    global layers_dict
    layers_dict = {}
    for layer in range(number_of_layers):
        layers_dict[layer] = {
            'numbers': [],
            'labels': [],
            'colors': [],
        }

    # print('layers_dict:')
    # print(json.dumps(layers_dict, indent=4))
    # print('-' * 64)

    form_layers_dict(subject_dict, 0, zero_layer=True)

    # print('layers_dict:')
    # print(json.dumps(layers_dict, indent=4))
    # print('-' * 64)

    global labels_font_size
    if labels_font_size is None:
        labels_font_size = labels_font_size_map.get(number_of_layers, labels_font_size_in_other_cases)

    fig, ax = plt.subplots()
    for layer in layers_dict:
        ax.pie(
            layers_dict[layer]['numbers'],
            labels=layers_dict[layer]['labels'],
            radius=(scale / number_of_layers) * (layer + 1),
            labeldistance=1,
            wedgeprops=dict(width=(scale / number_of_layers), edgecolor='w'),
            textprops={'fontsize': labels_font_size},
            colors=layers_dict[layer]['colors']
        )

    top_text = f'{day}'
    if day1:
        top_text += f'\n{day1}'

    ax.text(
        -2.1,
        1.5,
        top_text,
        horizontalalignment='left',
        verticalalignment='top',
        fontsize=11
    )

    bottom_text = f'total\naddressings:\n{len(list_of_subject_paths)}'
    ax.text(
        -2.1,
        -1.5,
        bottom_text,
        horizontalalignment='left',
        verticalalignment='bottom',
        fontsize=6
    )

    with io.BytesIO() as bytes_stream:
        plt.savefig(
            bytes_stream,
            dpi=dpi,
            format=format  # jpg, svg...
        )
        image_in_bytes = bytes_stream.getvalue()
    return image_in_bytes
